"""Fixed transports for reviewed templates, interactions and component cards.

This module owns transport only. Existing builders and independent acceptors own
native behavior. Preparation never runs a probe; dispatch is explicit, serial,
single-use and requires the newly frozen elevated helper (or an admin shell).
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EX = ROOT / 'tools/game-executor'
TA = EX / 'template-authoring'
TABS = EX / 'native-options'
OUTPUT = ROOT / '.runtime/native-card-20261017/prepared'
LEVEL = 1073741843
# The 1845 demo is explicitly authorized by the user on 2026-10-22. The
# historical 1843 route remains available to its existing reviewed callers.
# Other old levels, including protected 1842 and 1844, are not admitted here.
# Level identity comes from the reviewed build/spec, never a mutable module
# global chosen by a caller. Component owners still have their original 1843
# contract; only typed definitions and generalized interaction tabs are extended.
PARAMETERIZED_LEVELS = frozenset((LEVEL, 1073741845))
ROUTES = {
    'template-item': dict(root=ROOT / '.runtime/template-authoring/prepared-item',
        kind='template-item-build-v1', wrapper='invoke-item-probe.ps1',
        scope='FIXED_TEMPLATE_ITEM_ACTION', action=6, protocol=10,
        review='item_review', accept='accept_item'),
    'template-currency': dict(root=ROOT / '.runtime/template-authoring/prepared-currency',
        kind='template-currency-build-v1', wrapper='invoke-currency-probe.ps1',
        scope='FIXED_TEMPLATE_CURRENCY_ACTION', action=5, protocol=9,
        review='template_review', accept='accept_currency'),
    'role-template-bag': dict(root=ROOT / '.runtime/template-authoring/prepared-role-template-bag',
        kind='role-template-bag-build-v1', wrapper='invoke-role-template-bag-probe.ps1',
        scope='FIXED_ROLE_TEMPLATE_BAG_ACTION', action=10, protocol=14,
        review='role_template_bag_review', accept='accept_role_template_bag'),
    'generalized-tabs': dict(root=ROOT / '.runtime/native-options/prepared',
        kind='generalized-tabs-build-v1', wrapper='invoke-generalized-tabs.ps1',
        scope='FIXED_GENERALIZED_TABS_ACTION', action=13, protocol=18),
    'mondstadt-dropstuff': dict(root=ROOT / '.runtime/mondstadt-native/dropstuff/prepared',
        kind='mondstadt-dropstuff-build-v1', wrapper='invoke-mondstadt-dropstuff.ps1',
        scope='FIXED_MONDSTADT_DROPSTUFF_ACTION', action=20, protocol=25,
        componentFolder=ROOT / 'tools/mondstadt/life/dropstuff'),
    'mondstadt-combat': dict(root=ROOT / '.runtime/mondstadt-native/combat/prepared',
        kind='mondstadt-combat-build-v1', wrapper='invoke-mondstadt-combat.ps1',
        scope='FIXED_MONDSTADT_COMBAT_ACTION', action=21, protocol=26,
        componentFolder=ROOT / 'tools/mondstadt/combat/native'),
}
CONSUMED = ('dispatch.claim', 'launch.claim', 'attempt.used', 'exit.json')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def target_level(tool, level):
    allowed = {LEVEL} if 'componentFolder' in ROUTES[tool] else PARAMETERIZED_LEVELS
    require(type(level) is int and level in allowed, 'ONLY_EXPLICITLY_AUTHORIZED_CARD_LEVEL')
    return level


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def json_unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'DUPLICATE_JSON_KEY:' + key)
        result[key] = value
    return result


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=json_unique)


def write(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def ordinary(path, boundary=None, *, directory=False):
    raw = str(path)
    require('\0' not in raw and len(raw) <= 2048, 'CARD_PATH_INVALID')
    # Windows GetFullPath/abspath may silently remove trailing dots first.
    # Reject the caller spelling before canonicalization, then check ancestors.
    raw_parts = Path(raw).parts
    for part in raw_parts[1:] if Path(raw).anchor else raw_parts:
        require(not part.endswith((' ', '.')) and ':' not in part and
                re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I) is None,
                'CARD_PATH_ALIAS')
    value = Path(os.path.abspath(raw))
    for part in value.parts[1:]:
        require(not part.endswith((' ', '.')) and ':' not in part and
                re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I) is None,
                'CARD_PATH_ALIAS')
    if boundary is not None:
        base = Path(os.path.abspath(boundary))
        require(value != base and value.is_relative_to(base), 'CARD_PATH_OUTSIDE_ROOT')
    for current in (value, *value.parents):
        info = current.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'CARD_REPARSE_PATH')
    require(value.is_dir() if directory else value.is_file(), 'CARD_PATH_TYPE')
    return value


def load_module(name, folder=TA):
    # Fixed module names only. No caller-selectable Python entry points.
    require(name in {'item_review', 'template_review', 'accept_item', 'accept_currency',
                     'role_template_bag_review', 'accept_role_template_bag',
                     'verify_generalized_receipt', 'request', 'native_profiles',
                     'build_readonly_profile'}, 'MODULE_NOT_FIXED')
    for directory in (EX, folder):
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
    return __import__(name)


def utc(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(stamp.tzinfo is not None, 'CARD_TIMEZONE_REQUIRED')
    return stamp


def identity_header(path, action, session):
    content = Path(path).read_text(encoding='utf-8')
    result = {}
    for key in ('HR_ACTION', 'HR_NONCE', 'HR_DEADLINE', 'HR_MESSAGE_ID', 'HR_TARGET_PID', 'HR_TARGET_TID',
                'HR_TARGET_CREATION', 'HR_TARGET_THREAD_CREATION'):
        matches = re.findall(r'^#define ' + key + r' ([0-9]+)(?:ULL)?$', content, re.M)
        require(len(matches) == 1, 'HEADER_IDENTITY_MISSING:' + key)
        result[key] = int(matches[0])
    require(result['HR_ACTION'] == action and result['HR_NONCE'] > 0, 'HEADER_ACTION_IDENTITY')
    require(0xc000 <= result['HR_MESSAGE_ID'] <= 0xffff, 'HEADER_REGISTERED_MESSAGE_RANGE')
    for key, field in (('HR_TARGET_PID', 'pid'), ('HR_TARGET_TID', 'tid'),
                       ('HR_TARGET_CREATION', 'processCreation'), ('HR_TARGET_THREAD_CREATION', 'threadCreation')):
        require(result[key] == session[field], 'HEADER_SESSION_MISMATCH:' + field)
    image = re.findall(r'^#define HR_TARGET_IMAGE L(.+)$', content, re.M)
    require(len(image) == 1 and json.loads(image[0]) == session['image'], 'HEADER_IMAGE_MISMATCH')
    return dict(nonce=result['HR_NONCE'], deadline=result['HR_DEADLINE'],
                messageId=result['HR_MESSAGE_ID'])


def component_prepared(tool, source, built, *, fresh=False):
    """Admit an owner-built production card, never a compile-only stub.

    The two fixed owners implement the business operation and its independent
    raw decoder. This envelope binds their spec, baseline, sources and native
    identity; it cannot turn a missing implementation into a launchable card.
    """
    route = ROUTES[tool]
    prepared = read(source / 'prepared.json')
    require(prepared.get('kind') == route['kind'].replace('-build-', '-prepared-') and
            prepared.get('launchable') is True and prepared.get('compileOnly') is False and
            prepared.get('reviewed') is True and prepared.get('allowWrites') is True,
            'COMPONENT_PRODUCTION_PREPARED_REQUIRED')
    require({'prepared.json', 'normalized-spec.json', 'receipt-layout.json'} <= built['hashes'].keys(),
            'COMPONENT_ARTIFACT_SET_INCOMPLETE')
    expected = dict(actionCode=route['action'], receiptVersion=route['protocol'],
                    levelId=LEVEL, scope=route['scope'], wrapperName=route['wrapper'])
    for key, value in expected.items():
        require(prepared.get(key) == built.get(key) == value, 'COMPONENT_BINDING:' + key)
    for key in ('session', 'nonce', 'deadline', 'messageId', 'expiresUtc', 'baselineRun',
                'baselineSha256', 'normalizedSpecSha256', 'sourceHashes'):
        require(key in prepared and prepared[key] == built.get(key), 'COMPONENT_BUILD_BINDING:' + key)
    require(type(prepared['nonce']) is int and prepared['nonce'] > 0 and
            type(prepared['deadline']) is int and prepared['deadline'] > 0, 'COMPONENT_NATIVE_IDENTITY')
    require(type(prepared['messageId']) is int and 0xc000 <= prepared['messageId'] <= 0xffff,
            'COMPONENT_REGISTERED_MESSAGE_RANGE')
    require(digest(source / 'normalized-spec.json') == prepared['normalizedSpecSha256'] and
            read(source / 'normalized-spec.json').get('levelId') == LEVEL, 'COMPONENT_SPEC_CHANGED')
    require(digest(source / 'baseline-snapshot.bin') == prepared['baselineSha256'],
            'COMPONENT_BASELINE_CHANGED')
    decoder = ordinary(route['componentFolder'] / 'native_acceptance.py', ROOT)
    relative = decoder.relative_to(ROOT).as_posix()
    require(prepared['sourceHashes'].get(relative) == digest(decoder), 'COMPONENT_ACCEPTOR_NOT_PINNED')
    baseline = ordinary(prepared['baselineRun'], ROOT / '.runtime', directory=True)
    ro = load_module('build_readonly_profile', EX)
    accepted = ro.decode_run(baseline)
    require(accepted.get('ok') is True and accepted.get('levelObservation', {}).get('verified') is True and
            accepted['levelObservation'].get('levelId') == LEVEL, 'COMPONENT_BASELINE_NOT_ACCEPTED')
    record, _ = ro.load_decoder().read_probe(baseline / 'stdout.jsonl')
    snapshot_bytes = bytes.fromhex(record['snapshotHex'])
    require(hashlib.sha256(snapshot_bytes).hexdigest() == prepared['baselineSha256'],
            'COMPONENT_BASELINE_RAW_MISMATCH')
    baseline_prepared = read(baseline / 'prepared.json')
    for key in ('pid', 'tid', 'processCreation', 'threadCreation', 'image', 'window'):
        require(key in prepared['session'] and
                baseline_prepared.get('session', {}).get(key) == prepared['session'][key],
                'COMPONENT_BASELINE_SESSION_MISMATCH:' + key)
    if fresh:
        finished = utc(read(baseline / 'exit.json')['finishedUtc'])
        require(-5 <= (datetime.now(timezone.utc) - finished).total_seconds() <= 900,
                'COMPONENT_BASELINE_STALE')
    return prepared


def component_acceptance(tool, source, prepared):
    # A fixed file per owner; no request-selected Python import or entry point.
    path = ordinary(ROUTES[tool]['componentFolder'] / 'native_acceptance.py', ROOT)
    relative = path.relative_to(ROOT).as_posix()
    require(prepared['sourceHashes'].get(relative) == digest(path), 'COMPONENT_ACCEPTOR_CHANGED')
    spec = importlib.util.spec_from_file_location('_fixed_' + tool.replace('-', '_') + '_acceptor', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    native = module.validate_run(source)
    require(type(native) is dict and native.get('ok') is True and
            native.get('mutationVerified') is True and native.get('prefixPreserved') is True and
            native.get('configurationVerified') is True, 'COMPONENT_RAW_ACCEPTANCE_INCOMPLETE')
    for key, expected in dict(levelId=LEVEL, actionCode=ROUTES[tool]['action'],
                              receiptVersion=ROUTES[tool]['protocol'],
                              specSha256=digest(source / 'normalized-spec.json'),
                              rawSha256=digest(source / 'stdout.jsonl')).items():
        require(native.get(key) == expected, 'COMPONENT_ACCEPTANCE_BINDING:' + key)
    return native


def source_manifest(tool, source, *, fresh=False):
    route = ROUTES[tool]
    source = ordinary(source, route['root'], directory=True)
    built = read(ordinary(source / 'build-result.json'))
    require(built.get('kind') == route['kind'] and built.get('ok') is True and
            built.get('launchable') is True and built.get('compileOnly') is False and
            built.get('compiled') is True and built.get('run') == str(source) and
            built.get('actionCode') == route['action'], 'FIXED_LAUNCHABLE_BUILD_REQUIRED')
    hashes = built.get('hashes')
    required = {'target_config.h', 'baseline-snapshot.bin', 'hook_receipt_probe.exe',
                'hook_receipt.dll', route['wrapper']}
    require(type(hashes) is dict and required <= hashes.keys(), 'BUILD_ARTIFACT_SET_INCOMPLETE')
    for name, expected in hashes.items():
        path = ordinary(source / name, source)
        require(digest(path) == expected, 'BUILD_ARTIFACT_CHANGED:' + name)
    if 'componentFolder' in route:
        prepared = component_prepared(tool, source, built, fresh=fresh)
        expires = prepared['expiresUtc']
    elif tool == 'generalized-tabs':
        prepared = built
        require(built.get('layoutOnly') is False and built.get('componentKind') == 17 and
                built.get('receiptVersion') == route['protocol'], 'TABS_PROFILE_NOT_KIND17')
        require({'normalized-spec.json', 'receipt-layout.json'} <= hashes.keys(), 'TABS_ARTIFACT_SET')
        require(built.get('wrapper') == str(source / route['wrapper']) and
                built.get('wrapperSha256') == digest(source / route['wrapper']), 'WRAPPER_CHANGED')
        spec = read(source / 'normalized-spec.json')
        level = target_level(tool, built.get('levelId'))
        require(spec.get('levelId') == level, 'TABS_LEVEL_MISMATCH')
        require(digest(ordinary(built['spec'])) == built['specSha256'] and
                digest(source / 'normalized-spec.json') == built['normalizedSpecSha256'], 'TABS_SPEC_CHANGED')
        expires = built['expiresUtc']
    else:
        prepared = read(source / 'prepared.json')
        level = target_level(tool, prepared.get('levelId'))
        require(prepared.get('kind') == route['kind'].replace('-build-', '-prepared-') and
                prepared.get('actionCode') == route['action'] and
                ('levelId' not in built or built['levelId'] == level) and
                prepared.get('launchable') is True and prepared.get('reviewed') is True and
                prepared.get('allowWrites') is True and prepared.get('receiptVersion') == route['protocol'],
                'TEMPLATE_PREPARED_CONTRACT')
        require(prepared.get('wrapperName') == built.get('wrapperName') == route['wrapper'], 'WRAPPER_CHANGED')
        for key in ('reviewSha256', 'requestSha256', 'nonce', 'deadline'):
            require(built.get(key) == prepared.get(key), 'TEMPLATE_BUILD_BINDING:' + key)
        require(digest(source / 'review.json') == prepared['reviewSha256'] and
                digest(source / 'request.json') == prepared['requestSha256'], 'TEMPLATE_REQUEST_CHANGED')
        require(read(source / 'request.json').get('levelId') == level and
                read(source / 'review.json').get('levelId') == level,
                'TEMPLATE_REQUEST_LEVEL_MISMATCH')
        expires = prepared['reviewExpiresUtc']
        if fresh:
            reviewed = load_module(route['review']).validate_review(source / 'review.json')
            require(reviewed['reviewSha256'] == prepared['reviewSha256'], 'TEMPLATE_REVIEW_CHANGED')
    target_level(tool, prepared.get('levelId'))
    for name, expected in prepared['sourceHashes'].items():
        source_file = ordinary(ROOT / name, ROOT)
        require(digest(source_file) == expected, 'BUILD_SOURCE_CHANGED:' + name)
    session = prepared['session']
    identity = identity_header(source / 'target_config.h', route['action'], session)
    if 'componentFolder' in route:
        require(all(identity[key] == prepared[key] for key in ('nonce', 'deadline', 'messageId')),
                'COMPONENT_HEADER_BINDING')
    if fresh:
        require(datetime.now(timezone.utc) < utc(expires), 'CARD_EXPIRED')
        profiles = load_module('native_profiles', EX)
        profiles.validate_session(session)
        kernel, _ = profiles.windows_api()
        require(int(kernel.GetTickCount64()) < identity['deadline'], 'NATIVE_DEADLINE_EXPIRED')
    return source, built, prepared, dict(session=session, expiresUtc=expires, **identity)


def prepare(tool, source):
    source, built, prepared, identity = source_manifest(tool, source, fresh=True)
    require(not any((source / name).exists() for name in CONSUMED), 'SOURCE_ALREADY_CONSUMED')
    # One source build may be wrapped only once, even across separate invocations.
    root = OUTPUT / tool
    root.mkdir(parents=True, exist_ok=True)
    ordinary(root, ROOT / '.runtime', directory=True)
    run = root / uuid.uuid4().hex
    run.mkdir()
    write(source / 'native-card.claim', dict(run=str(run), tool=tool, buildSha256=digest(source / 'build-result.json')))
    card = dict(schema=1, kind='fixed-native-card-v1', tool=tool, run=str(run), sourceRun=str(source),
        sourceBuildSha256=digest(source / 'build-result.json'), sourceHashes=prepared['sourceHashes'],
        wrapperSha256=digest(source / ROUTES[tool]['wrapper']), levelId=prepared['levelId'], launchable=True,
        compileOnly=False, createdUtc=datetime.now(timezone.utc).isoformat(), **identity)
    write(run / 'prepared.json', card)
    return dict(ok=True, **card, nativeCalled=False, preparedSha256=digest(run / 'prepared.json'))


def manifest(run, expected_tool=None, *, fresh=False):
    run = ordinary(run, OUTPUT, directory=True)
    card = read(run / 'prepared.json')
    tool = card.get('tool')
    require(tool in ROUTES and (expected_tool is None or tool == expected_tool), 'CARD_TOOL_MISMATCH')
    level = target_level(tool, card.get('levelId'))
    require(run.parent == OUTPUT / tool and card.get('kind') == 'fixed-native-card-v1' and
            card.get('schema') == 1 and card.get('run') == str(run),
            'CARD_CONTRACT')
    source, built, prepared, identity = source_manifest(tool, card['sourceRun'], fresh=fresh)
    require(digest(source / 'build-result.json') == card['sourceBuildSha256'] and
            digest(source / ROUTES[tool]['wrapper']) == card['wrapperSha256'] and
            prepared['sourceHashes'] == card['sourceHashes'] and
            prepared.get('levelId') == level, 'CARD_SOURCE_BINDING')
    for key, value in identity.items():
        require(card.get(key) == value, 'CARD_IDENTITY_CHANGED:' + key)
    claim = read(source / 'native-card.claim')
    require(claim == dict(run=str(run), tool=tool, buildSha256=card['sourceBuildSha256']), 'SOURCE_CARD_CLAIM_CHANGED')
    return run, card, source


def cleanup(run, card, source):
    route = ROUTES[card['tool']]
    end = read(source / 'exit.json')
    require(end.get('scope') == route['scope'], 'WRAPPER_SCOPE_MISMATCH')
    if end.get('executed') is False:
        require(not (source / 'attempt.used').exists(), 'ATTEMPT_DESPITE_REFUSAL')
        return True, False
    require(end.get('executed') is True, 'NATIVE_EXECUTION_UNKNOWN')
    records = [json.loads(line, object_pairs_hook=json_unique) for line in
               (source / 'stdout.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    require(len(records) == 1, 'ONE_NATIVE_RECEIPT_REQUIRED')
    raw = records[0]
    require(raw.get('scope') == route['scope'] and raw.get('selfTestOnly') is False and
            raw.get('pid') == card['session']['pid'] and raw.get('tid') == card['session']['tid'] and
            raw.get('receiptNonce') == str(card['nonce']) and raw.get('receiptDeadline') == str(card['deadline']) and
            raw.get('receiptProtocol') == route['protocol'], 'RAW_CARD_IDENTITY_MISMATCH')
    clean = (raw.get('probeElevatedHigh') is True and raw.get('transportOk') is True and
             raw.get('unhooked') is True and raw.get('callbackCount') == 1 and
             raw.get('activeCallbacks') == 0 and raw.get('hostPostUnhookPings') == 0)
    return clean, True


def acceptance(run, card, source):
    tool = card['tool']
    clean, executed = cleanup(run, card, source)
    level = target_level(tool, card.get('levelId'))
    result = dict(ok=False, tool=tool, run=str(run), sourceRun=str(source), levelId=level,
        cleanupVerified=clean, nativeStarted=executed, called=executed, safeToRelease=False,
        outcomeUncertain=executed, replayForbidden=True, persistentSaveVerified=False,
        gameplayVerified=False, rawSha256=digest(source / 'stdout.jsonl') if (source / 'stdout.jsonl').is_file() else None)
    if not executed:
        return dict(result, error=read(source / 'exit.json').get('error'), safeToRelease=clean, outcomeUncertain=False)
    require(clean, 'NATIVE_CLEANUP_NOT_CONFIRMED')
    if 'componentFolder' in ROUTES[tool]:
        native = component_acceptance(tool, source, read(source / 'prepared.json'))
        write(run / 'native-acceptance.json', native)
    elif tool == 'generalized-tabs':
        verify = load_module('verify_generalized_receipt', TABS)
        try:
            native = verify.verify(source, source / 'receipt-layout.json', source / 'normalized-spec.json',
                                   run / 'native-acceptance.json')
        except verify.ReceiptRefusal as error:
            raise ValueError('TABS_RAW_ACCEPTANCE:' + str(error)) from error
        require(native.get('ok') is True and not native.get('unresolved'), 'TABS_ACCEPTANCE_INCOMPLETE')
    else:
        native = load_module(ROUTES[tool]['accept']).validate_run(source)
        if tool == 'role-template-bag':
            require(native.get('ok') is True and native.get('bindingVerified') is True,
                    'ROLE_TEMPLATE_BAG_NOT_VERIFIED')
            prepared = read(source / 'prepared.json')
            require(native.get('requestSha256') == prepared['requestSha256'] and
                    native.get('reviewSha256') == prepared['reviewSha256'],
                    'ROLE_TEMPLATE_BAG_ACCEPTANCE_BINDING')
        else:
            require(native.get('ok') is True and native.get('catalogRegisteredVerified') is True,
                    'TEMPLATE_CATALOG_NOT_VERIFIED')
        require(native.get('levelId') == level, 'NATIVE_ACCEPTANCE_LEVEL_MISMATCH')
        write(run / 'native-acceptance.json', native)
    require(native.get('levelId') == level, 'NATIVE_ACCEPTANCE_LEVEL_MISMATCH')
    # The legacy native flag means a mutation was attempted, not that a verified
    # catalog delta has an unknown ID. Preserve it separately, never discard it.
    result.update(ok=True, safeToRelease=True, outcomeUncertain=False, nativeAcceptance=native,
                  nativeReportedOutcomeUncertain=native.get('outcomeUncertain'),
                  limits='Transport and native readback only; template properties, save and gameplay require their own evidence.')
    if tool in ('template-item', 'template-currency'):
        result.update(createdId=native['createdId'], catalogRegisteredVerified=True,
                      nameVerified=False, defaultsVerified=False)
    elif tool == 'role-template-bag':
        result.update(bindingVerified=True, entityId=native['entityId'],
                      templateId=native['templateId'], componentId=native['componentId'],
                      limits='Role template backpack binding verified; save and runtime inventory require their own evidence.')
    return result


def uncertainty(run):
    claimed = False
    clean = False
    try:
        path, card, source = manifest(run)
        claimed = any((path / name).exists() or (source / name).exists() for name in CONSUMED)
        if claimed:
            clean, executed = cleanup(path, card, source)
            if not executed:
                claimed = False
    except (OSError, ValueError, KeyError, TypeError):
        # Missing or changed identity after admission is never a safe retry.
        path = Path(run)
        claimed = claimed or (path / 'dispatch.claim').exists() or (path / 'map-queue-claim.json').exists()
    return dict(nativeStarted=claimed, called=claimed, cleanupVerified=clean if claimed else True,
                outcomeUncertain=claimed, safeToRelease=not claimed, replayForbidden=True)


def dispatch(tool, run, *, queue=None, direct=False):
    require(bool(queue) != bool(direct), 'EXACTLY_ONE_TRANSPORT_REQUIRED')
    run, card, source = manifest(run, tool, fresh=not bool(queue))
    if queue:
        spec = importlib.util.spec_from_file_location('_fixed_native_card_queue', HERE.parent / 'elevated-request.py')
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
        return client.send_native_map(tool, run, queue_dir=Path(queue), timeout=300)
    require(os.name == 'nt' and ctypes.windll.shell32.IsUserAnAdmin() != 0, 'DIRECT_ADMIN_REQUIRED')
    require(not any((run / name).exists() or (source / name).exists() for name in CONSUMED),
            'CARD_ALREADY_CONSUMED_DO_NOT_REPLAY')
    profiles = load_module('native_profiles', EX)
    profiles.verify_disk(profiles.load_profile())
    host = profiles.powershell_host()
    write(run / 'dispatch.claim', dict(startedUtc=datetime.now(timezone.utc).isoformat(),
                                     wrapperSha256=card['wrapperSha256'], host=host))
    env = os.environ.copy()
    env['PSModulePath'] = str(Path(host['path']).parent / 'Modules')
    invoked = subprocess.run([host['path'], '-NoProfile', '-NonInteractive', '-File',
                              str(source / ROUTES[tool]['wrapper'])], cwd=source,
                             stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=300,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    (run / 'dispatch.stdout.txt').write_bytes(invoked.stdout)
    (run / 'dispatch.stderr.txt').write_bytes(invoked.stderr)
    result = acceptance(run, card, source)
    require(invoked.returncode == 0 or result['ok'] is False, 'WRAPPER_EXIT_DISAGREES')
    write(run / 'result.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--tool', choices=ROUTES, required=True)
    prep.add_argument('--source-run', type=Path, required=True)
    for tool in ROUTES:
        child = commands.add_parser(tool)
        child.add_argument('--run', type=Path, required=True)
        group = child.add_mutually_exclusive_group(required=True)
        group.add_argument('--direct-elevated', action='store_true')
        group.add_argument('--elevated-queue', type=Path)
    args = parser.parse_args(argv)
    try:
        result = (prepare(args.tool, args.source_run) if args.command == 'prepare' else
                  dispatch(args.command, args.run, queue=args.elevated_queue, direct=args.direct_elevated))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, RuntimeError) as error:
        result = dict(ok=False, error=str(error), **(uncertainty(args.run) if hasattr(args, 'run') else
                      dict(nativeStarted=False, outcomeUncertain=False, cleanupVerified=True, safeToRelease=True)))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result.get('ok') is True else 2


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
