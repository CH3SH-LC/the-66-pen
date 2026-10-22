"""Compile/verify a common map placement offline, without moving terrain owners."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import placement
from cli import write_new
from placement import wf


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('compile', 'compile-fixture'):
        p = sub.add_parser(name)
        p.add_argument('--points', required=True)
        p.add_argument('--out', required=True)
        p.add_argument('--quantization', choices=('exact', 'nearest'), required=True)
        p.add_argument('--preferred-translation', type=float, nargs=3, default=[0., 0., 0.])
        p.add_argument('--world-translation', type=float, nargs=3)
        if name == 'compile':
            p.add_argument('--catalog-run', required=True)
            p.add_argument('--expected-identity-sha256')
        else:
            p.add_argument('--fixture', required=True)
    sub.add_parser('verify').add_argument('--compiled', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'verify':
            compiled, _ = wf.read_json(wf.project_path(args.compiled, 'compiled'))
            summary = placement.verify_compilation(compiled)
        else:
            doc_path = wf.project_path(args.points, 'points')
            document, digest = wf.read_json(doc_path)
            kwargs = dict(quantization=args.quantization, preferred_translation=args.preferred_translation,
                          world_translation=args.world_translation)
            if args.command == 'compile':
                result = placement.compile_points(args.catalog_run, document,
                    expected_identity_sha256=args.expected_identity_sha256, **kwargs)
            else:
                fixture, _ = wf.read_json(wf.project_path(args.fixture, 'fixture'))
                result = placement.compile_fixture(fixture, document, **kwargs)
            wf.require(wf.read_json(doc_path)[1] == digest, 'POINT_DOCUMENT_CHANGED_DURING_COMPILATION')
            output = write_new(args.out, result)
            summary = dict(ok=True, output=output, mode=result['mode'], pointCount=result['pointCount'],
                compilationSha256=result['compilationSha256'], pointDocumentFileSha256=digest,
                worldTranslation=result['worldTranslation'], nativeCalled=False, gameAccepted=False)
        print(json.dumps(summary, ensure_ascii=False, allow_nan=False))
        return 0
    except wf.FrameError as error:
        print(json.dumps(error.result(), ensure_ascii=False, allow_nan=False))
        return 2
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps(dict(ok=False, code='PLACEMENT_IO_OR_SCHEMA_ERROR', error=str(error),
                              nativeCalled=False, nativeExecuted=False, gameAccepted=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
