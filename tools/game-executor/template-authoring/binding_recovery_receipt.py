"""Independent raw acceptance for closing one failed empty-bag edit transaction."""
import struct

import binding_receipt as prior_api
import component_receipt as components
import receipt as catalogs
from receipt import require, pointer

# MSVC x64 layout; no normal-binding receipt is rewritten as successful.
LEGACY_RECEIPT_BYTES = 148552
RECEIPT_BYTES = 148560
EXPECTED_AT, AFTER_AT, WORK_AT, RESULT_AT = 24, 33232, 66440, 98752
BEFORE_COMPONENTS_AT, AFTER_COMPONENTS_AT = 76000, 87376
EDIT_AT = RESULT_AT + 56
SNAPSHOT_BYTES = 33208
RESULT_BYTES = 49808
STATE_OFFSETS = (80, 12496, 24912, 37328)


def decode(raw):
    require(type(raw) is bytes and len(raw) in (LEGACY_RECEIPT_BYTES, RECEIPT_BYTES), 'RECOVERY_RAW_SIZE')
    native = prior_api.values(raw, 0, '<6I', 'size version sehCode afterSceneUnchanged priorHashVerified reserved')
    require(native['size'] == len(raw) and (native['version'], len(raw)) in
            ((1, LEGACY_RECEIPT_BYTES), (2, RECEIPT_BYTES)), 'RECOVERY_RAW_VERSION')
    if native['version'] == 2: native['tokenRefusalHashVerified'] = native.pop('reserved')
    result = prior_api.values(raw, RESULT_AT, '<I', 'code')
    result.update(prior_api.flags(raw, RESULT_AT + 4,
        'identityVerified emptyReferenceVerified tokenVerified transactionClosed needsBinding outcomeUncertain'))
    result.update(prior_api.values(raw, RESULT_AT + 16, '<3Qi', 'emptyReference tokenClass tokenLabel tokenDepth'))
    result['tokenFlags'] = struct.unpack_from('<2B', raw, RESULT_AT + 44)
    result.update(prior_api.values(raw, RESULT_AT + 48, '<2I', 'emptyReferenceClassification emptyReferenceId'))
    if native['version'] == 2:
        result.update(prior_api.values(raw, LEGACY_RECEIPT_BYTES, '<I', 'recoveryVersion'))
        result.update(prior_api.flags(raw, LEGACY_RECEIPT_BYTES + 4,
            'pendingScopeVerified closeCoreCalled closeCoreReturned originalTokenUnused'))
    edit = prior_api.values(raw, EDIT_AT, '<2IQ', 'code stage transaction')
    edit.update(prior_api.flags(raw, EDIT_AT + 16,
        'openCalled snapshotCalled notifyCalled closeCalled snapshotVerified notificationVerified closeVerified transactionMayBeOpen outcomeUncertain needsPersistenceAcceptance'))
    evidence = prior_api.values(raw, EDIT_AT + 32, '<5Qi', 'moduleBase global owner wrapper config kind')
    evidence.update(prior_api.flags(raw, EDIT_AT + 76, 'codeAndThreadVerified'))
    return {'native': native, 'result': result, 'edit': edit, 'evidence': evidence}


def _state(raw, edit_at, relative, wrapper):
    return prior_api.decode_state(raw[edit_at + relative:edit_at + relative + prior_api.STATE_BYTES], wrapper)


def verify_prior(raw, *, identity=None):
    """Only a definite null-reference result, before any setter/notification."""
    d = prior_api.decode_native(raw)
    n, a, at, b, e = (d[k] for k in ('native', 'action', 'attachment', 'binding', 'edit'))
    require(n['sehCode'] == n['readbackSehCode'] == n['nativeCode'] == n['metadataUsageInProgress'] == 0 and
            n['afterSceneUnchanged'] == 1 and n['metadataCallsStarted'] == n['metadataCallsCompleted'] == 17 and
            n['nativeCallAttempted'] and n['componentMutationCalled'] and n['runtimeStateMayHaveChanged'], 'RECOVERY_PRIOR_NATIVE')
    require(a['code'] == 19 and a['stage'] == 4 and all(a[k] for k in
            ('catalogVerified', 'templateVerified', 'componentVerified', 'outcomeUncertain')) and
            not a['reused'] and not a['postBindingVerified'] and not a['entry'] and not a['shopIndex'], 'RECOVERY_PRIOR_ACTION')
    require(a['templateId'] & 0xe0000000 == 0x40000000 and (a['templateId'] >> 22) & 127 == 11 and
            a['entityId'] > 0 and a['componentId'] > 0 and all(pointer(a[k]) for k in
            ('owner', 'wrapper', 'config', 'templateResource')), 'RECOVERY_PRIOR_IDENTITY')
    if identity is not None:
        require(all(identity[k] == a[k] for k in ('entityId', 'templateId', 'componentId', 'owner', 'wrapper', 'config')) and
                identity['transaction'] == e['transaction'], 'RECOVERY_LOCKED_IDENTITY')
    require(at['code'] == 1 and all(at[k] for k in ('attachCalled', 'beforeVerified', 'afterVerified')) and
            at['returned'] == a['wrapper'] and at['row'][:5] == (a['wrapper'], n['classes'][2], a['config'], n['classes'][0], 33),
            'RECOVERY_PRIOR_ATTACHMENT')
    require(b['code'] == 3 and b['stage'] == 0 and b['referenceFactoryCalled'] and
            b['reference'] == b['entry'] == b['shopIndex'] == 0 and not any(b[k] for k in
            ('referenceReadbackVerified', 'addCalled', 'entryIndexReadbackVerified', 'setterCalled', 'fieldReadbackVerified',
             'dependencyRefreshCalled', 'mutationCalled', 'outcomeUncertain', 'needsOwnerNotification')), 'RECOVERY_PRIOR_BINDING')
    require(e['code'] == 8 and e['stage'] == 0 and pointer(e['transaction']) and
            all(e[k] for k in ('openCalled', 'snapshotCalled', 'snapshotVerified', 'transactionMayBeOpen', 'outcomeUncertain', 'needsPersistenceAcceptance')) and
            not any(e[k] for k in ('notifyCalled', 'closeCalled', 'notificationVerified', 'closeVerified')), 'RECOVERY_PRIOR_EDIT')
    evidence = d['evidence']
    require(evidence['owner'] == a['owner'] and evidence['wrapper'] == a['wrapper'] and evidence['config'] == a['config'] and
            evidence['kind'] == 33 and evidence['codeAndThreadVerified'], 'RECOVERY_PRIOR_EDIT_IDENTITY')
    before, snapshot = (_state(raw, prior_api.EDIT_AT, off, a['wrapper']) for off in STATE_OFFSETS[:2])
    require(before['count'] == before['targetCount'] == 0 and before['depth'] == before['baseDepth'] and
            snapshot['count'] == snapshot['targetCount'] == 1 and snapshot['depth'] == before['depth'] + 1 and
            snapshot['target'][2] == a['wrapper'] and snapshot['target'][3] == snapshot['target'][5] == 0 and
            pointer(snapshot['target'][4]), 'RECOVERY_PRIOR_PENDING')
    empty = d['observed'][0]
    require(pointer(empty['reference']) and all(empty[k] == 0 for k in ('templateId', 'entry', 'shopCount', 'shopIndex')),
            'RECOVERY_PRIOR_EMPTY_REFERENCE')
    components.verify_component_transition(
        raw[prior_api.BEFORE_COMPONENTS_AT:prior_api.BEFORE_COMPONENTS_AT + components.COMPONENT_BYTES],
        raw[prior_api.AFTER_ATTACH_AT:prior_api.AFTER_ATTACH_AT + components.COMPONENT_BYTES],
        raw[prior_api.FINAL_COMPONENTS_AT:prior_api.FINAL_COMPONENTS_AT + components.COMPONENT_BYTES],
        owner=a['owner'], kind=33, wrapper_class=n['classes'][2], config_class=n['classes'][0],
        wrapper=a['wrapper'], config=a['config'], attach_called=True)
    old, new = [catalogs.decode_catalog(raw[at:at + catalogs.CATALOG_BYTES].hex()) for at in
                (prior_api.BEFORE_CATALOG_AT, prior_api.AFTER_CATALOG_AT)]
    require(all(old[k] == new[k] for k in ('levelId', 'global', 'manager', 'primary', 'companion')) and
            old['global'] == evidence['global'] and old['primary'].get(a['templateId']) ==
            (a['templateId'], 12, a['templateResource'], n['classes'][3]), 'RECOVERY_PRIOR_CATALOG')
    return d


def verify_token_refusal(raw, prior_raw, *, identity=None):
    d = decode(raw); prior = verify_prior(prior_raw, identity=identity)
    n, r, e = d['native'], d['result'], d['edit']
    require(n['version'] == 1 and n['size'] == LEGACY_RECEIPT_BYTES and n['sehCode'] == n['reserved'] == 0 and
            n['afterSceneUnchanged'] == n['priorHashVerified'] == 1, 'RECOVERY_REFUSAL_NATIVE')
    require(r['code'] == 5 and all(r[k] for k in ('identityVerified', 'emptyReferenceVerified', 'needsBinding', 'outcomeUncertain')) and
            not r['tokenVerified'] and not r['transactionClosed'] and not e['notifyCalled'] and not e['closeCalled'] and
            e['transactionMayBeOpen'] and r['emptyReference'] == prior['observed'][0]['reference'] and
            r['emptyReferenceClassification'] == r['emptyReferenceId'] == 0, 'RECOVERY_REFUSAL_SHAPE')
    require(raw[EDIT_AT:EDIT_AT + prior_api.EDIT_BYTES] ==
            prior_raw[prior_api.EDIT_AT:prior_api.EDIT_AT + prior_api.EDIT_BYTES], 'RECOVERY_REFUSAL_ORIGINAL_EDIT')
    # Fields following tokenClass were never read in v1's early refusal.
    # Their zero-initialized bytes provide no observation of the original token.
    return d


def verify_pending_diagnostic(raw, prior_raw, token_refusal_raw, *, identity=None):
    d = decode(raw); prior = verify_prior(prior_raw, identity=identity)
    verify_token_refusal(token_refusal_raw, prior_raw, identity=identity)
    n, r, e = d['native'], d['result'], d['edit']
    require(n['version'] == 2 and n['sehCode'] == 0 and
            n['afterSceneUnchanged'] == n['priorHashVerified'] == n['tokenRefusalHashVerified'] == 1 and
            r['code'] == 10 and r['recoveryVersion'] == 2 and r['identityVerified'] and r['emptyReferenceVerified'] and
            r['originalTokenUnused'] and not r['tokenVerified'] and not r['transactionClosed'] and
            not r['closeCoreCalled'] and not r['closeCoreReturned'] and e['code'] == 3 and e['stage'] == 0 and
            not e['notifyCalled'] and not e['closeCalled'] and e['transactionMayBeOpen'], 'RECOVERY_PENDING_DIAGNOSTIC')
    require(d['evidence'] == prior['evidence'] and e['transaction'] == prior['edit']['transaction'] and
            r['emptyReference'] == prior['observed'][0]['reference'] and r['emptyReferenceClassification'] == r['emptyReferenceId'] == 0,
            'RECOVERY_PENDING_IDENTITY')
    wrapper = prior['action']['wrapper']
    for off in STATE_OFFSETS[:2]:
        require(raw[EDIT_AT + off:EDIT_AT + off + prior_api.STATE_BYTES] ==
                prior_raw[prior_api.EDIT_AT + off:prior_api.EDIT_AT + off + prior_api.STATE_BYTES], 'RECOVERY_PENDING_ORIGINAL_STATE')
    original = _state(prior_raw, prior_api.EDIT_AT, STATE_OFFSETS[1], wrapper)
    current = _state(raw, EDIT_AT, STATE_OFFSETS[2], wrapper)
    require(current['count'] == 2 and current['version'] == original['version'] + 1 and
            all(current[k] == original[k] for k in original if k not in ('count', 'version', 'records')) and
            current['records'][:1] == original['records'], 'RECOVERY_PENDING_EXACT_APPEND')
    added = current['records'][1]
    require(pointer(added[0]) and pointer(added[1]) and added[0] != original['records'][0][0] and
            added[1] != original['recordClass'] and added[2:] == (0, 0, 0, 0), 'RECOVERY_PENDING_APPENDED_IDENTITY')
    return current


def verify(raw, prior_raw, token_refusal_raw, pending_diagnostic_raw, *, identity=None):
    d = decode(raw); prior = verify_prior(prior_raw, identity=identity)
    verify_token_refusal(token_refusal_raw, prior_raw, identity=identity)
    reviewed = verify_pending_diagnostic(pending_diagnostic_raw, prior_raw, token_refusal_raw, identity=identity)
    n, r, e = d['native'], d['result'], d['edit']
    require(n['version'] == 2 and n['sehCode'] == 0 and
            n['afterSceneUnchanged'] == n['priorHashVerified'] == n['tokenRefusalHashVerified'] == 1,
            'RECOVERY_NATIVE_INCOMPLETE')
    require(r['code'] == 8 and all(r[k] for k in
            ('identityVerified', 'emptyReferenceVerified', 'transactionClosed', 'needsBinding', 'outcomeUncertain',
             'pendingScopeVerified', 'closeCoreCalled', 'closeCoreReturned', 'originalTokenUnused')) and
            r['recoveryVersion'] == 2 and not r['tokenVerified'],
            'RECOVERY_RESULT_INCOMPLETE')
    require(d['evidence'] == prior['evidence'], 'RECOVERY_EDIT_IDENTITY_CHANGED')
    require(e['transaction'] == prior['edit']['transaction'] and e['code'] == 13 and e['stage'] == 0 and
            all(e[k] for k in ('openCalled', 'snapshotCalled', 'notifyCalled', 'closeCalled', 'snapshotVerified',
                'notificationVerified', 'closeVerified', 'outcomeUncertain', 'needsPersistenceAcceptance')) and
            not e['transactionMayBeOpen'], 'RECOVERY_EDIT_NOT_CLOSED')
    wrapper = prior['action']['wrapper']
    for off in STATE_OFFSETS[:2]:
        require(raw[EDIT_AT + off:EDIT_AT + off + prior_api.STATE_BYTES] ==
                prior_raw[prior_api.EDIT_AT + off:prior_api.EDIT_AT + off + prior_api.STATE_BYTES], 'RECOVERY_PRIOR_STATE_CHANGED')
    before, snapshot, notified, closed = [_state(raw, EDIT_AT, off, wrapper) for off in STATE_OFFSETS]
    require(all(all(s[key] == before[key] for key in ('manager', 'list', 'recordClass', 'literal', 'baseDepth'))
                for s in (snapshot, notified, closed)), 'RECOVERY_MANAGER_CHANGED')
    require(notified['depth'] == snapshot['depth'] == before['depth'] + 1 and
            closed['depth'] == before['depth'] and closed['count'] == closed['targetCount'] == 0, 'RECOVERY_DEPTH_OR_PENDING')
    require(notified['count'] == 2 and notified['targetCount'] == 1 and notified['version'] == reviewed['version'] and
            notified['records'] == [(*reviewed['records'][0][:5], 1), reviewed['records'][1]], 'RECOVERY_NOTIFY_RECORD_DELTA')
    require(r['emptyReferenceClassification'] == r['emptyReferenceId'] == 0 and
            r['emptyReference'] == prior['observed'][0]['reference'] and r['tokenClass'] == r['tokenLabel'] == r['tokenDepth'] == 0 and
            r['tokenFlags'] == (0, 0), 'RECOVERY_UNUSED_TOKEN_OR_EMPTY_REFERENCE')
    blocks = [(prior_raw, prior_api.AFTER_ATTACH_AT), (prior_raw, prior_api.FINAL_COMPONENTS_AT),
              (raw, BEFORE_COMPONENTS_AT), (raw, AFTER_COMPONENTS_AT)]
    snapshots = [components.decode_components(data[at:at + components.COMPONENT_BYTES]) for data, at in blocks]
    first = snapshots[0]
    # Native notification may update only the target wrapper's inherited enable.
    for index, snap in enumerate(snapshots[1:]):
        require(all(snap[k] == first[k] for k in ('owner', 'ownerClass', 'ownerState', 'set', 'list', 'kinds')),
                'RECOVERY_COMPONENT_IDENTITY')
        require(snap['count'] == first['count'], 'RECOVERY_COMPONENT_SET')
        for old, row in zip(first['rows'], snap['rows']):
            require(row == old or index == 2 and row[4] == 33 and row[:5] == old[:5], 'RECOVERY_COMPONENT_CHANGED')
    target = [row for row in first['rows'] if row[4] == 33]
    require(len(target) == 1 and target[0][:5] == prior['attachment']['row'][:5], 'RECOVERY_TARGET_COMPONENT')
    return {'editTransactionClosed': True, 'ownerNotificationVerified': True, 'emptyBagRetained': True,
            'needsBinding': True, 'bindingVerified': False, 'persistentSaveVerified': False, 'gameplayVerified': False,
            'outcomeUncertain': True, 'entityId': prior['action']['entityId'], 'componentId': prior['action']['componentId'],
            'templateId': prior['action']['templateId'], 'transaction': e['transaction'],
            'closeStrategy': 'reviewed-mixed-scope-core', 'closeCoreVerified': True, 'originalTokenUnused': True, 'tokenVerified': False,
            'reviewedPendingCount': 2, 'additionalRecordIdentityPreservedBeforeClose': True, 'additionalRecordPayloadVerified': False}
