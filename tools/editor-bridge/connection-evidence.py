"""Classify a read-only Windows TCP snapshot; never open or repair a connection.

Input rows use Get-NetTCPConnection property names with State rendered as text.
This reports OS transport evidence only, not a protocol handshake or current level.
"""
import argparse
import ipaddress
import json
from pathlib import Path


def endpoint(address, port):
    value = ipaddress.ip_address(address)
    if value.version == 6 and value.ipv4_mapped:
        value = value.ipv4_mapped
    if not value.is_loopback:
        return None
    return str(value), int(port)


def classify(rows, editor_pid, game_pid):
    if editor_pid <= 0 or game_pid <= 0 or editor_pid == game_pid:
        raise ValueError('Distinct positive process identities required')
    selected = []
    for row in rows:
        owner = int(row['OwningProcess'])
        if owner not in (editor_pid, game_pid) or row['State'] != 'Established':
            continue
        local = endpoint(row['LocalAddress'], row['LocalPort'])
        remote = endpoint(row['RemoteAddress'], row['RemotePort'])
        if local is not None and remote is not None:
            selected.append((owner, local, remote))
    editor = [r for r in selected if r[0] == editor_pid]
    game = [r for r in selected if r[0] == game_pid]
    pairs = [dict(editorLocal=list(e[1]), gameLocal=list(e[2]))
             for e in editor if e[1] != e[2]
             and any(g[1] == e[2] and g[2] == e[1] for g in game)]
    return dict(scope='os-loopback-tcp-snapshot-only',
                editorPid=editor_pid, gamePid=game_pid,
                reciprocalPairObserved=bool(pairs), pairs=pairs,
                editorSelfConnectionObserved=any(e[1] == e[2] for e in editor),
                protocolHandshakeVerified=False, currentLevelVerified=False,
                notice='Absence is not proof about other transports. A pair alone does not authorize writes.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--editor-pid', type=int, required=True)
    parser.add_argument('--game-pid', type=int, required=True)
    args = parser.parse_args()
    source = json.loads(args.snapshot.read_text(encoding='utf-8-sig'))
    result = classify(source['endpoints'], args.editor_pid, args.game_pid)
    result['observedUtc'] = source.get('observedUtc')
    print(json.dumps(result, ensure_ascii=False, indent=2))
