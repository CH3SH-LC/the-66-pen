"""One complete v2 module batch plus unchanged v1 compatibility suite."""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(HERE / 'tests')]
import placement
import test_placement
import test_world_frame


def main():
    output = ROOT / '.runtime/world-frame-20261017' / ('placement-batch-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    output.mkdir(parents=True)
    log = io.StringIO()
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(test_placement),
                               unittest.defaultTestLoader.loadTestsFromModule(test_world_frame)])
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    raw = log.getvalue().encode('utf-8')
    (output / 'unittest.log').write_bytes(raw)
    paths = list(placement.DEPENDENCIES) + [HERE / name for name in (
        'placement_cli.py', 'PLACEMENT.md', 'cli.py', 'tests/test_placement.py',
        'tests/run_placement_batch.py', 'tests/test_world_frame.py')]
    hashes = {str(path.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    summary = dict(schema='world-placement-offline-batch-v2', ok=result.wasSuccessful(), tests=result.testsRun,
                   failures=len(result.failures), errors=len(result.errors), sources=hashes,
                   logSha256=hashlib.sha256(raw).hexdigest(), output=str(output),
                   privateFixturesOnly=True, gameAccess=False, desktopAccess=False, queueAccess=False)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary))
    if not result.wasSuccessful():
        print(log.getvalue())
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
