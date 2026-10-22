"""Run the one final module batch and retain raw log plus exact source hashes."""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(HERE / "tests")]
import test_world_frame


def main():
    output = ROOT / ".runtime/world-frame-20261017" / ("final-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(parents=True)
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_world_frame)
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    log = stream.getvalue(); (output / "unittest.log").write_text(log, encoding="utf-8")
    owned = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(HERE.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}
    summary = dict(schema="world-frame-final-offline-batch-v1", ok=result.wasSuccessful(),
                   testsRun=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                   privateCatalogFixturesOnly=True, nativeCalled=False, gameAccepted=False,
                   sourceSha256=owned, rawLogSha256=hashlib.sha256(log.encode("utf-8")).hexdigest(),
                   output=str(output))
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    if not result.wasSuccessful():
        print(log)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
