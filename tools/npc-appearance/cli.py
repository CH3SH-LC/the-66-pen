"""Read-only NPC source and exact template identity tools. No dispatch action."""
import argparse
import json
import sys
from pathlib import Path
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from official_models import Catalog, ROOT, require


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    q = sub.add_parser('resolve')
    q.add_argument('--template-id', action='append', type=int, required=True)
    sub.add_parser('coverage')
    q = sub.add_parser('npc-records')
    q.add_argument('--npc-id', action='append', type=int)
    q = sub.add_parser('saved-readback')
    q.add_argument('--gil', required=True)
    q.add_argument('--sha256', required=True)
    q.add_argument('--entity-id', action='append', type=int, required=True)
    # Each result has an optional exclusive output below this module's own root.
    for parser in sub.choices.values():
        parser.add_argument('--out')
    a = p.parse_args(argv)
    try:
        catalog = Catalog()
        if a.action == 'resolve':
            result = catalog.resolve(a.template_id)
        elif a.action == 'coverage':
            result = catalog.npc_coverage()
        elif a.action == 'npc-records':
            require(a.npc_id or a.out, 'FULL_NPC_RECORDS_REQUIRE_OUTPUT_FILE')
            ids = a.npc_id or sorted(catalog.npcs)
            require(len(set(ids)) == len(ids) and all(x in catalog.npcs for x in ids),
                    'NPC_SELECTION_INVALID')
            result = dict(kind='npc-appearance-native-npc-prefix-v1', ok=True,
                rows=[catalog.npcs[x] for x in ids], sourceContract=catalog.contract_evidence,
                sources={k:v for k,v in catalog.sources.items() if k in ('npcs','npcIndex')},
                fullNpcRecordDecoded=False, beyondPlacementSupported=False,
                appearanceVerified=False, gameProcessAccessed=False,
                nativeCalled=False, gameWritesPerformed=False)
        else:
            from saved_readback import inspect
            result = inspect(a.gil, a.sha256, a.entity_id, catalog)
        result.update(called=False, outcomeUncertain=False, dispatchAttempted=False)
        if a.out:
            out = Path(a.out).resolve()
            require(out.is_relative_to(ROOT / '.runtime/npc-appearance-20261017') and
                    not out.exists(), 'NEW_OWNED_OUTPUT_REQUIRED')
            for parent in (out.parent, *out.parent.parents):
                if parent.exists():
                    require(not parent.is_symlink() and not
                        (getattr(parent.stat(), 'st_file_attributes', 0) & 0x400),
                        'OUTPUT_REPARSE_REFUSED')
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open('x', encoding='utf8') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
            print(json.dumps(dict(ok=True, result=str(out), kind=result['kind'],
                gameProcessAccessed=False, nativeCalled=False, gameWritesPerformed=False)))
        else:
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps(dict(ok=False, error=str(exc), called=False,
            outcomeUncertain=False, dispatchAttempted=False,
            gameProcessAccessed=False, gameWritesPerformed=False), ensure_ascii=False))
        return 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf8')
    raise SystemExit(main())
