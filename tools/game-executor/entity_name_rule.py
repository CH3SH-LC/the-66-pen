"""templateId -> the entity name a native create is expected to persist.

Offline lookup only. No game process, no elevation, no GIL is written. Importable
(``name_for(template_id)``) or runnable as a CLI.

THE RULE (measured; evidence in docs/research/entity-create/ENTITY-NAME-RULE.md)

  The native placement factory this project creates through
  (``ge::scene::place_builtin``, tools/game-executor/native/scene_calls.cpp) takes
  geometry and a template id and NOTHING ELSE. The name that later appears in the
  saved .gil is therefore the game's own name for that template: the ``name`` field
  the editor's materialized prefab registry reports for the same id (read-only
  bridge operation ``prefab-catalog``, tools/editor-bridge/Adapter/SceneCatalog.cs).

  So for a create that passes no name and is not renamed afterwards:

      expectedName == directory[templateId]

  This is option (a): the directory's name field. It is NOT a fixed pattern.

COUNTEREXAMPLE THAT DEFINES THE BOUNDARY

  A creator that writes its own name overrides the default. The project's offline
  transplant tool (tools/editor-bridge/build-static-level-draft.py,
  make_entry()) writes ``MW_Static_P{n}_Tile{k}`` for its placements, and those are
  exactly the names in the saved GILs. A later rename does the same (the CRUD probe
  renames its entity to ``MW_CRUD_Probe``). See the rule doc for the measured split.

WHAT THIS DIRECTORY IS NOT

  * NOT injective. 421 of the 1097 distinct names are shared by two or more template
    ids ('乔木' alone covers 72 ids, '灌木' 58, '山石' 40). A name never proves a
    template id; the template id must be checked separately, as
    verify-created-save.py does.
  * NOT total. 3 registryIds carry an empty name (1000000, 1000001, 10003001) and
    verify-created-save.py refuses an empty --name, so those cannot be verified this
    way at all.
  * NOT version-free. It is the 7.1.0 CN client. A different client build may
    renumber ids or rename prefabs; re-capture and re-freeze instead of reusing.

  Usage:
    python -B tools/game-executor/entity_name_rule.py search "乔木" --limit 10
    python -B tools/game-executor/entity_name_rule.py show --template-id 20001002
    python -B tools/game-executor/entity_name_rule.py list --limit 5
    python -B tools/game-executor/entity_name_rule.py verify
    python -B tools/game-executor/entity_name_rule.py freeze --out NEW.json \
        --catalog RAW1.json --catalog RAW2.json

  Exit 0 on success, 1 on a refused or failed lookup, 2 on invalid CLI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / 'docs/research/entity-create/prefab-name-directory.json'
DIRECTORY_SHA256 = 'da34c6ecba1edadd4a634adacbeaf29e3ef7b8b94b66090a801e52dee0707d40'
# Raw captures the frozen directory was derived from, for re-verification.
RAW_CAPTURES = {
    ROOT / '.runtime/editor-bridge/elevated-interfaces-p02-571b9f753bb0467aa39fc7f71951a52f'
    / '2dfcea43f9904b71b6b6ccc42c94f47e.response.json':
        'c9d22bf4d56420974ff6dcdaedeef641bed4147e48d85e5a1bd402542e3f2c61',
    ROOT / '.runtime/verification/interface-experiments-20260928/geometry-fix/prefab-catalog-r219.json':
        '46faaa35cdd58c38cb513b865e06e48ef9bc8b865e11927ea5db0ab5698726f3',
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_directory(path: Path | None = None, *, verify: bool = True) -> dict:
    """Return the frozen templateId -> name directory.

    Raises ValueError when the file is missing, is not this schema, or (unless
    verify=False) does not match the digest this tool was frozen against.
    """
    path = Path(path) if path else DIRECTORY
    if not path.is_file():
        raise ValueError(f'name directory not found: {path}')
    if verify and path.resolve() == DIRECTORY.resolve():
        actual = _digest(path)
        if actual != DIRECTORY_SHA256:
            raise ValueError('name directory digest changed: '
                             f'{actual} != {DIRECTORY_SHA256}; re-freeze deliberately rather '
                             'than trusting an edited copy')
    document = json.loads(path.read_text(encoding='utf-8'))
    if document.get('kind') != 'prefab-name-directory' or not isinstance(document.get('names'), dict):
        raise ValueError(f'not a prefab-name-directory document: {path}')
    return document


def names(path: Path | None = None) -> dict[int, str]:
    document = load_directory(path)
    return {int(key): value for key, value in document['names'].items()}


def name_for(template_id: int, path: Path | None = None) -> str | None:
    """The expected saved entity name for a nameless native create, or None."""
    if not isinstance(template_id, int) or isinstance(template_id, bool):
        raise ValueError('template id must be an int')
    return names(path).get(template_id)


def require_name(template_id: int, path: Path | None = None) -> str:
    """Like name_for, but raises instead of returning None or an empty name."""
    value = name_for(template_id, path)
    if value is None:
        raise ValueError(f'template id {template_id} is not in the prefab name directory')
    if not value:
        raise ValueError(f'template id {template_id} has an empty catalog name; '
                         'verify-created-save.py cannot accept an empty --name')
    return value


def describe(template_id: int, path: Path | None = None) -> dict:
    document = load_directory(path)
    value = document['names'].get(str(template_id))
    if value is None:
        raise ValueError(f'template id {template_id} is not in the prefab name directory')
    return {'templateId': template_id, 'expectedName': value, 'nameIsEmpty': value == '',
            'directory': str(Path(path) if path else DIRECTORY),
            'directorySha256': _digest(Path(path) if path else DIRECTORY),
            'profileId': document.get('profileId'), 'derivedFrom': document.get('derivedFrom')}


def duplicates(path: Path | None = None) -> dict[str, list[int]]:
    """Names carried by more than one template id: why a name cannot identify a template."""
    grouped: dict[str, list[int]] = {}
    for template_id, value in names(path).items():
        if value:
            grouped.setdefault(value, []).append(template_id)
    return {value: sorted(ids) for value, ids in grouped.items() if len(ids) > 1}


def freeze(output: Path, catalogs: list[Path]) -> dict:
    """Derive a frozen directory from raw prefab-catalog captures.

    Refuses to overwrite an existing file and refuses captures that disagree, so a
    re-freeze is always a deliberate, reviewable act.
    """
    if output.exists():
        raise ValueError(f'refusing to overwrite existing file: {output}')
    if not catalogs:
        raise ValueError('at least one --catalog capture is required')
    derived, merged = [], None
    for catalog in catalogs:
        raw = Path(catalog).read_bytes()
        document = json.loads(raw.decode('utf-8-sig'))
        if document.get('status') != 'prefab-catalog-read-only':
            raise ValueError(f'not a prefab-catalog capture: {catalog}')
        mapping = {str(row['registryId']): row['name'] for row in document['prefabs']}
        if merged is None:
            merged = mapping
        elif merged != mapping:
            differing = [key for key in set(merged) | set(mapping) if merged.get(key) != mapping.get(key)]
            raise ValueError(f'captures disagree on {len(differing)} ids, e.g. {sorted(differing)[:5]}')
        derived.append({'label': catalog.name, 'path': str(catalog).replace('\\', '/'),
                        'sha256': hashlib.sha256(raw).hexdigest(), 'total': len(mapping)})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump({'schema': 1, 'kind': 'prefab-name-directory',
                   'profileId': 'genshin-cn-7.1.0-prefab-name-directory-v1',
                   'derivedFrom': derived,
                   'usage': 'templateId -> saved entity name for a native create that passes no name',
                   'caveats': ['not injective: a name never proves a template id',
                               'empty names cannot be verified',
                               'an explicit name or a later rename overrides this value',
                               '7.1.0 CN only'],
                   'total': len(merged), 'names': merged},
                  stream, ensure_ascii=False, indent=1)
        stream.write('\n')
    return {'path': str(output), 'sha256': _digest(output), 'total': len(merged)}


def _report_verify() -> dict:
    document = load_directory()
    digest_ok = _digest(DIRECTORY) == DIRECTORY_SHA256
    raws = []
    for path, expected in RAW_CAPTURES.items():
        if path.is_file():
            actual = _digest(path)
            raws.append({'path': str(path), 'sha256': actual, 'matchesPinned': actual == expected})
        else:
            raws.append({'path': str(path), 'missing': True})
    grouped = duplicates()
    empty = [key for key, value in document['names'].items() if value == '']
    widest = max(grouped.items(), key=lambda item: len(item[1]), default=None)
    return {'directory': str(DIRECTORY), 'sha256': _digest(DIRECTORY),
            'pinnedSha256': DIRECTORY_SHA256, 'digestOk': digest_ok,
            'total': document['total'], 'emptyNames': empty,
            'namesSharedByMultipleIds': len(grouped),
            'widestDuplicateGroup': ({'name': widest[0], 'count': len(widest[1]),
                                      'templateIds': widest[1][:8]} if widest else None),
            'rawCaptures': raws}


def search(query: str, *, offset: int = 0, limit: int = 20) -> dict:
    """Bounded name/id lookup in the pinned native registry, not a placement claim."""
    if not isinstance(query, str) or not query.strip() or len(query) > 64:
        raise ValueError('query must contain 1..64 characters')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('offset must be nonnegative and limit must be 1..100')
    document = load_directory()
    needle = query.strip().casefold()
    matches = [{'templateId': int(key), 'name': name}
               for key, name in sorted(document['names'].items(), key=lambda item: int(item[0]))
               if needle in name.casefold() or needle in key]
    page = matches[offset:offset + limit]
    return {'query': query, 'totalInSource': len(document['names']), 'matched': len(matches),
            'rows': page, 'offset': offset, 'limit': limit,
            'nextOffset': offset + len(page) if offset + len(page) < len(matches) else None,
            'source': str(DIRECTORY.relative_to(ROOT)).replace('\\', '/'),
            'profileId': document['profileId'], 'sourceSha256': _digest(DIRECTORY),
            'nativeMutationsPerformed': False, 'placementVerified': False,
            'warning': 'Names can match several template ids. This frozen registry is a lookup source, not current placement or component acceptance.'}


def main() -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    show = sub.add_parser('show', help='expected name for one template id')
    show.add_argument('--template-id', type=int, required=True)
    show.add_argument('--directory', type=Path)
    listing = sub.add_parser('list', help='list the directory')
    listing.add_argument('--limit', type=int, default=20)
    listing.add_argument('--duplicates', action='store_true')
    searching = sub.add_parser('search', help='bounded Chinese-name or template-id search; offline only')
    searching.add_argument('query')
    searching.add_argument('--offset', type=int, default=0)
    searching.add_argument('--limit', type=int, default=20)
    check = sub.add_parser('verify', help='re-verify the frozen directory and its captures')
    make = sub.add_parser('freeze', help='derive a frozen directory from raw captures')
    make.add_argument('--out', type=Path, required=True)
    make.add_argument('--catalog', type=Path, action='append', default=[])
    args = parser.parse_args()

    try:
        if args.command == 'search':
            print(json.dumps(search(args.query, offset=args.offset, limit=args.limit), ensure_ascii=False, indent=2))
            return 0
        if args.command == 'show':
            if not 0 < args.template_id <= 0xffffffff:
                parser.error('template id must be a nonzero uint32')
            result = describe(args.template_id, args.directory)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0
        if args.command == 'list':
            document = load_directory()
            if args.duplicates:
                grouped = duplicates()
                rows = [{'name': value, 'count': len(ids), 'templateIds': ids[:8]}
                        for value, ids in sorted(grouped.items(), key=lambda x: -len(x[1]))]
                print(json.dumps({'namesSharedByMultipleIds': len(grouped),
                                  'rows': rows[:args.limit]}, ensure_ascii=True, indent=2))
                return 0
            rows = [{'templateId': int(key), 'name': value}
                    for key, value in sorted(document['names'].items(), key=lambda x: int(x[0]))]
            print(json.dumps({'total': len(rows), 'rows': rows[:args.limit]},
                             ensure_ascii=True, indent=2))
            return 0
        if args.command == 'verify':
            result = _report_verify()
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0 if result['digestOk'] else 1
        if args.command == 'freeze':
            print(json.dumps(freeze(args.out, args.catalog), ensure_ascii=True, indent=2))
            return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=True))
        return 1
    parser.error('unhandled command')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
