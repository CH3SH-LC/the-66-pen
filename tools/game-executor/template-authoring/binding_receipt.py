"""Pure decoding of the version-2 binding receipt, including native edit records.

MSVC layout: task-ba/binding-layout.json. Success still requires the separately
validated dispatch envelope; these records do not prove save or gameplay.
"""
import struct

import component_receipt as components
import receipt as catalogs

require, pointer = catalogs.require, catalogs.pointer
RECEIPT_BYTES = 988064
ACTION_AT, EXPECTED_AT, AFTER_AT, WORK_AT = 112, 50040, 83248, 116456
EDIT_AT, EDIT_BYTES, STATE_BYTES = ACTION_AT + 184, 49744, 12416
BEFORE_CATALOG_AT, AFTER_CATALOG_AT = WORK_AT + 303248, WORK_AT + 565552
BEFORE_COMPONENTS_AT = WORK_AT + 827856 + 9560
AFTER_ATTACH_AT = BEFORE_COMPONENTS_AT + components.COMPONENT_BYTES
FINAL_COMPONENTS_AT = WORK_AT + 860168
BEFORE_BINDING_AT, AFTER_BINDING_AT = WORK_AT + 871544, WORK_AT + 871576
RECORD = struct.Struct('<5QB7x')
METADATA_CALLS = 19  # Ordinary binding: historical 17 plus typed pool/reset groups.


def values(raw, at, fmt, names):
    return dict(zip(names.split(), struct.unpack_from(fmt, raw, at)))


def flags(raw, at, names):
    names = names.split()
    result = values(raw, at, '<' + 'B' * len(names), ' '.join(names))
    require(all(v in (0, 1) for v in result.values()), 'BINDING_BOOL_ENCODING')
    return {k: bool(v) for k, v in result.items()}


def decode_native(raw):
    require(type(raw) is bytes and len(raw) == RECEIPT_BYTES, 'BINDING_RAW_SIZE')
    native = values(raw, 0, '<9I', 'size version sehCode readbackSehCode afterSceneUnchanged nativeCode metadataUsageInProgress metadataCallsStarted metadataCallsCompleted')
    require(native['size'] == RECEIPT_BYTES and native['version'] == 2, 'BINDING_NATIVE_VERSION')
    native['classes'] = struct.unpack_from('<8Q', raw, 40)
    native.update(flags(raw, 104, 'nativeCallAttempted componentMutationCalled runtimeStateMayHaveChanged'))
    action = values(raw, ACTION_AT, '<5I', 'code stage entityId templateId componentId')
    action.update(values(raw, ACTION_AT + 24, '<5Qi', 'owner templateResource wrapper config entry shopIndex'))
    action.update(flags(raw, ACTION_AT + 176, 'catalogVerified templateVerified componentVerified reused postBindingVerified catalogsUnchanged needsOwnerNotification outcomeUncertain'))
    attachment = values(raw, ACTION_AT + 72, '<I', 'code')
    attachment['row'] = components.ROW.unpack_from(raw, ACTION_AT + 80)
    attachment['returned'] = struct.unpack_from('<Q', raw, ACTION_AT + 120)[0]
    attachment.update(flags(raw, ACTION_AT + 128, 'attachCalled beforeVerified afterVerified outcomeUncertain'))
    binding = values(raw, ACTION_AT + 136, '<2I2Qi', 'code stage reference entry shopIndex')
    binding.update(flags(raw, ACTION_AT + 164, 'referenceFactoryCalled referenceReadbackVerified addCalled entryIndexReadbackVerified setterCalled fieldReadbackVerified dependencyRefreshCalled needsDependencyRefresh mutationCalled outcomeUncertain needsOwnerNotification'))
    edit = values(raw, EDIT_AT, '<2IQ', 'code stage transaction')
    edit.update(flags(raw, EDIT_AT + 16, 'openCalled snapshotCalled notifyCalled closeCalled snapshotVerified notificationVerified closeVerified transactionMayBeOpen outcomeUncertain needsPersistenceAcceptance'))
    evidence = values(raw, EDIT_AT + 32, '<5Qi', 'moduleBase global owner wrapper config kind')
    evidence.update(flags(raw, EDIT_AT + 76, 'codeAndThreadVerified'))
    observed = [values(raw, at, '<2Q2Ii', 'reference entry templateId shopCount shopIndex')
                for at in (BEFORE_BINDING_AT, AFTER_BINDING_AT)]
    return dict(native=native, action=action, attachment=attachment, binding=binding,
                edit=edit, evidence=evidence, observed=observed)


def decode_state(raw, wrapper):
    require(len(raw) == STATE_BYTES, 'BINDING_EDIT_STATE_SIZE')
    state = values(raw, 0, '<4I2i', 'code count version targetCount baseDepth depth')
    require(state['code'] == 0 and 0 <= state['count'] <= 256 and
            0 <= state['baseDepth'] <= state['depth'], 'BINDING_EDIT_STATE_INCOMPLETE')
    state['flags'] = struct.unpack_from('<3B', raw, 24)
    require(all(v in (0, 1) for v in state['flags']) and not any(state['flags'][1:]), 'BINDING_EDIT_BUSY')
    state.update(values(raw, 32, '<6Q', 'manager list items recordClass literal capacity'))
    require(all(pointer(state[k]) for k in ('manager', 'list', 'items', 'recordClass', 'literal')) and
            state['count'] <= state['capacity'] <= 4096, 'BINDING_EDIT_STATE_POINTERS')
    state['records'] = [RECORD.unpack_from(raw, 128 + i * RECORD.size) for i in range(state['count'])]
    require(all(pointer(r[0]) and pointer(r[1]) for r in state['records']) and
            len({r[0] for r in state['records']}) == state['count'], 'BINDING_EDIT_RECORDS')
    for row in state['records']:
        if row[1] == state['recordClass']:
            require(pointer(row[2]) and (row[3] == 0 or pointer(row[3])) and
                    (row[4] == 0 or pointer(row[4])) and row[5] in (0, 1), 'BINDING_EDIT_RECORD_FIELDS')
    matches = [r for r in state['records'] if r[1] == state['recordClass'] and r[2] == wrapper]
    require(len(matches) == state['targetCount'] <= 1, 'BINDING_EDIT_TARGET_COUNT')
    state['target'] = RECORD.unpack_from(raw, 80)
    require(state['target'] == (matches[0] if matches else (0, 0, 0, 0, 0, 0)), 'BINDING_EDIT_TARGET_COPY')
    return state


def verify_edit(raw, decoded, *, module_base, global_pointer, kind):
    edit, evidence, action = (decoded[k] for k in ('edit', 'evidence', 'action'))
    require(edit['code'] == 13 and edit['stage'] == 0 and pointer(edit['transaction']) and
            all(edit[k] for k in ('openCalled', 'snapshotCalled', 'notifyCalled', 'closeCalled',
                'snapshotVerified', 'notificationVerified', 'closeVerified', 'outcomeUncertain', 'needsPersistenceAcceptance')) and
            not edit['transactionMayBeOpen'], 'BINDING_EDIT_NOT_COMPLETE')
    require(evidence == {'moduleBase': module_base, 'global': global_pointer,
            'owner': action['owner'], 'wrapper': action['wrapper'], 'config': action['config'], 'kind': kind,
            'codeAndThreadVerified': True}, 'BINDING_EDIT_EVIDENCE')
    states = [decode_state(raw[EDIT_AT + offset:EDIT_AT + offset + STATE_BYTES], action['wrapper'])
              for offset in (80, 12496, 24912, 37328)]
    before, snapshot, notified, closed = states
    require(all(s['recordClass'] == decoded['native']['classes'][6] for s in states), 'BINDING_EDIT_RECORD_CLASS')
    require(all(all(s[key] == before[key] for key in ('manager', 'list', 'recordClass', 'literal', 'baseDepth'))
                for s in states[1:]), 'BINDING_EDIT_CONTEXT_CHANGED')
    require(before['depth'] == before['baseDepth'] and snapshot['depth'] == notified['depth'] == before['depth'] + 1 and
            closed['depth'] == before['depth'] and closed['count'] == 0, 'BINDING_EDIT_DEPTH_OR_PENDING')
    require(snapshot['targetCount'] == notified['targetCount'] == 1 and pointer(snapshot['target'][4]),
            'BINDING_EDIT_SNAPSHOT_MISSING')
    if not before['targetCount']:
        require(snapshot['count'] == before['count'] + 1 and snapshot['records'][:-1] == before['records'] and
                snapshot['target'] == snapshot['records'][-1] and snapshot['target'][3] == snapshot['target'][5] == 0,
                'BINDING_EDIT_SNAPSHOT_APPEND')
    else:
        require(snapshot['records'] == before['records'], 'BINDING_EDIT_EXISTING_RECORD_CHANGED')
    require(notified['count'] == snapshot['count'], 'BINDING_EDIT_NOTIFY_COUNT')
    for old, new in zip(snapshot['records'], notified['records']):
        expected = (*old[:5], 1) if old[0] == snapshot['target'][0] else old
        require(new == expected, 'BINDING_EDIT_NOTIFY_RECORD_DELTA')
    return {'ownerNotificationVerified': True, 'editTransactionClosed': True}


def verify_binding(raw, decoded, *, request, current):
    n, a, at, b = (decoded[k] for k in ('native', 'action', 'attachment', 'binding'))
    parameters = request['parameters']
    kind = 35 if request['action'] == 'bind-shop' else 33
    require(n['sehCode'] == n['readbackSehCode'] == n['nativeCode'] == n['metadataUsageInProgress'] == 0 and
            n['afterSceneUnchanged'] == 1 and n['metadataCallsStarted'] == n['metadataCallsCompleted'] == METADATA_CALLS and
            n['nativeCallAttempted'] and n['runtimeStateMayHaveChanged'] and
            all(pointer(p) for p in n['classes']), 'BINDING_NATIVE_NOT_COMPLETE')
    require(a['code'] in (0, 1) and a['stage'] == 5 and a['entityId'] == parameters['entityId'] and
            a['templateId'] == parameters['templateId'] and a['componentId'] > 0 and
            a['reused'] == (a['code'] == 1) and all(a[k] for k in
                ('catalogVerified', 'templateVerified', 'componentVerified', 'postBindingVerified', 'catalogsUnchanged')) and
            not a['needsOwnerNotification'], 'BINDING_ACTION_NOT_COMPLETE')
    require(all(pointer(a[k]) for k in ('owner', 'templateResource', 'wrapper', 'config')), 'BINDING_ACTION_POINTERS')
    matches = [row for row in current['entities'] if row['id'] == a['entityId']]
    require(len(matches) == 1 and int(matches[0]['owner'], 16) == a['owner'], 'BINDING_OWNER_NOT_IN_SCENE')
    global_pointer = int(current['pointers']['global'], 16)
    catalogs_raw = [raw[off:off + catalogs.CATALOG_BYTES] for off in (BEFORE_CATALOG_AT, AFTER_CATALOG_AT)]
    old_catalog, new_catalog = [catalogs.decode_catalog(data.hex()) for data in catalogs_raw]
    require(old_catalog['levelId'] == new_catalog['levelId'] == request['levelId'] and
            old_catalog['global'] == new_catalog['global'] == global_pointer and
            all(old_catalog[k] == new_catalog[k] for k in ('manager', 'primary', 'companion')),
            'BINDING_CATALOG_CHANGED')
    template = a['templateId']
    require(template & 0xe0000000 == 0x40000000 and (template >> 22) & 127 == (15 if kind == 35 else 11) and
            old_catalog['primary'].get(template) == (template, 17 if kind == 35 else 12,
                a['templateResource'], n['classes'][4 if kind == 35 else 3]), 'BINDING_TEMPLATE_IDENTITY')
    require(at['code'] == (1 if at['attachCalled'] else 0) and at['beforeVerified'] and
            (not at['attachCalled'] or at['afterVerified'] and at['returned'] == a['wrapper']) and
            at['row'][:5] == (a['wrapper'], n['classes'][2], a['config'], n['classes'][1 if kind == 35 else 0], kind),
            'BINDING_ATTACHMENT_RESULT')
    delta = components.verify_component_transition(
        raw[BEFORE_COMPONENTS_AT:BEFORE_COMPONENTS_AT + components.COMPONENT_BYTES],
        raw[AFTER_ATTACH_AT:AFTER_ATTACH_AT + components.COMPONENT_BYTES],
        raw[FINAL_COMPONENTS_AT:FINAL_COMPONENTS_AT + components.COMPONENT_BYTES],
        owner=a['owner'], kind=kind, wrapper_class=n['classes'][2],
        config_class=n['classes'][1 if kind == 35 else 0], wrapper=a['wrapper'], config=a['config'],
        attach_called=at['attachCalled'], allow_target_enable_change=not a['reused'])
    before, after = decoded['observed']
    require(after['templateId'] == template and pointer(after['reference']) and
            after['entry'] == a['entry'] and after['shopIndex'] == a['shopIndex'], 'BINDING_FIELD_READBACK')
    if kind == 35:
        require(after['shopCount'] == 1 and after['shopIndex'] > 0 and pointer(after['entry']), 'BINDING_SHOP_ENTRY')
    else:
        require(after['shopCount'] == after['shopIndex'] == after['entry'] == 0, 'BINDING_BAG_SINGLE_REFERENCE')
    if a['reused']:
        require(before == after and not at['attachCalled'] and not n['componentMutationCalled'] and
                not any(b[k] for k in ('referenceFactoryCalled', 'addCalled', 'setterCalled', 'mutationCalled')) and
                not any(decoded['edit'][k] for k in ('openCalled', 'snapshotCalled', 'notifyCalled', 'closeCalled')),
                'BINDING_REUSE_MUTATED')
        notification = {'ownerNotificationVerified': False, 'editTransactionClosed': False}
    else:
        require(before['templateId'] == before['shopCount'] == 0 and b['code'] == b['stage'] == 0 and
                b['reference'] == after['reference'] and b['entry'] == after['entry'] and b['shopIndex'] == after['shopIndex'] and
                all(b[k] for k in ('referenceFactoryCalled', 'referenceReadbackVerified', 'setterCalled', 'fieldReadbackVerified',
                    'mutationCalled', 'outcomeUncertain')) and n['componentMutationCalled'] and a['outcomeUncertain'] and
                b['addCalled'] == b['entryIndexReadbackVerified'] == (kind == 35) and
                not any(b[k] for k in ('dependencyRefreshCalled', 'needsDependencyRefresh', 'needsOwnerNotification')),
                'BINDING_SETTER_NOT_VERIFIED')
        notification = verify_edit(raw, decoded, module_base=int(current['pointers']['moduleBase'], 16),
                                   global_pointer=global_pointer, kind=kind)
    return dict(delta, **notification, bindingVerified=True, reused=a['reused'],
                entityId=a['entityId'], templateId=template, componentId=a['componentId'],
                shopIndex=a['shopIndex'], outcomeUncertain=a['outcomeUncertain'])
