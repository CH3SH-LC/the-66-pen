"""Offline tests for the read-only current-level discovery entry.

Everything here is local: no elevation, no UAC, no game, no editor, no helper. The parts
worth testing are the ones that made a real discovery run unfalsifiable in practice --
the launcher's cancellation detection and the wait that has to outlast a prompt -- plus
the handle resolver, which must never read outside its own runs directory.

    python -B tools/game-executor/tests/test_discover_current_level.py
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
TARGET = ROOT / 'tools/game-executor/discover_current_level.py'
POWERSHELL = Path(os.environ.get('MILIASTRA_POWERSHELL_HOST',
                                'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'))

FAILURES = []


def check(name, condition, detail=''):
    if condition:
        print('PASS  %s' % name)
    else:
        print('FAIL  %s %s' % (name, detail))
        FAILURES.append(name)


def load():
    spec = importlib.util.spec_from_file_location('discovery', TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


discovery = load()


def case_wait_covers_the_prompt():
    fake_sha = 'a' * 64
    probe = Path('C:/nonexistent/wrapper.ps1')
    # emit_launcher writes a file, so drive it in a temp dir.
    with tempfile.TemporaryDirectory() as temp:
        run = Path(temp)
        emitted = discovery.emit_launcher(run, probe, fake_sha,
                                          host={'path': str(POWERSHELL)})
        body = emitted.read_text(encoding='utf-8-sig')
    check('the launcher compares the OS cancel text, not only the error code',
          'Win32Exception 1223' in body and '.Contains($cancelText)' in body, body[-300:])
    check('the launcher still walks the inner-exception chain',
          'NativeErrorCode -eq 1223' in body)
    check('the launcher writes its result even when it never started',
          'finally' in body and 'launch-result.json' in body)


def case_wait_is_long_enough_for_a_prompt():
    check('the wait exceeds the observed 126.6 s prompt lifetime',
          discovery.WAIT_SECONDS > 126.6, str(discovery.WAIT_SECONDS))
    check('the wait is still bounded', discovery.WAIT_SECONDS <= 600,
          str(discovery.WAIT_SECONDS))
    # MEASURED: the default 180 s preparation TTL expired 50 s BEFORE the operator answered,
    # so the run was dead while its prompt was still on screen. The TTL must outlast our own
    # wait, or our clock -- not the operator -- decides the outcome.
    check('the preparation TTL outlasts our own wait',
          discovery.PREPARATION_TTL_SECONDS > discovery.WAIT_SECONDS,
          'ttl=%s wait=%s' % (discovery.PREPARATION_TTL_SECONDS, discovery.WAIT_SECONDS))
    check('the preparation TTL exceeds the default it replaced',
          discovery.PREPARATION_TTL_SECONDS > 180,
          str(discovery.PREPARATION_TTL_SECONDS))
    # MEASURED: 360 was refused with TTL_OUT_OF_RANGE. The pinned validator allows
    # 30 <= ttl <= 300 (build_readonly_profile.py:168). This assertion is what would have
    # stopped that mistake offline, instead of burning an operator's elevation prompt.
    check('the preparation TTL respects the engine ceiling of 300',
          discovery.PREPARATION_TTL_SECONDS <= 300,
          'the pinned validator refuses ttl_seconds > 300')
    check('the preparation TTL is above the engine floor of 30',
          discovery.PREPARATION_TTL_SECONDS >= 30)
    check('the wait stays inside the TTL window',
          discovery.WAIT_SECONDS < discovery.PREPARATION_TTL_SECONDS,
          'wait=%s ttl=%s' % (discovery.WAIT_SECONDS, discovery.PREPARATION_TTL_SECONDS))


def case_timeout_message_matches_the_constant():
    """A message that names a number the code no longer uses is a small lie. MEASURED:
    after raising the wait to 150 the message still said '90-second'."""
    text = TARGET.read_text(encoding='utf-8')
    check('no hardcoded wait number is left in the timeout message',
          '90-second wait elapsed' not in text, 'the literal 90-second is still present')
    check('the message interpolates the constant',
          "'%d-second wait elapsed" in text or '%d-second wait elapsed' in text)
    check('the constant is passed to prepare, not left at the default',
          'ttl_seconds=PREPARATION_TTL_SECONDS' in text)


def case_cancel_detection_actually_works():
    """Run the emitted launcher for real against a non-existent wrapper... no: against a
    real but harmless command, with elevation declined by construction is impossible
    offline. Instead prove the detection EXPRESSION is correct by evaluating it in
    PowerShell against the exact string the operating system produced."""
    os_text = subprocess.run(
        [str(POWERSHELL), '-NoProfile', '-Command',
         '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); '
         '(New-Object ComponentModel.Win32Exception 1223).Message'],
        capture_output=True, text=True, encoding='utf-8', timeout=120)
    cancel_text = (os_text.stdout or '').strip()
    check('the OS reports a non-empty cancel string', bool(cancel_text), repr(cancel_text))
    observed = ('由于出现以下错误，无法运行此命令: ' + cancel_text) if cancel_text else ''
    # The containment test the script performs, evaluated here on the real strings.
    expression = '[string]::IsNullOrEmpty($e) -eq $false -and $e.Contains($c)'
    result = subprocess.run(
        [str(POWERSHELL), '-NoProfile', '-Command',
         '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); '
         '$e = %s; $c = %s; %s' % (json.dumps(observed), json.dumps(cancel_text), expression)],
        capture_output=True, text=True, encoding='utf-8', timeout=120)
    check('the real cancelled message is recognised as a cancellation',
          (result.stdout or '').strip().lower() == 'true', (result.stdout or '').strip())
    result = subprocess.run(
        [str(POWERSHELL), '-NoProfile', '-Command',
         '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); '
         '$e = "some other failure"; $c = %s; %s' % (json.dumps(cancel_text), expression)],
        capture_output=True, text=True, encoding='utf-8', timeout=120)
    check('an unrelated failure is NOT reported as a cancellation (negative control)',
          (result.stdout or '').strip().lower() == 'false', (result.stdout or '').strip())


def case_handle_resolver_refuses_escape(tmp: Path):
    runs_root = (discovery.DEFAULT_OUTPUT_ROOT / 'runs')
    check('an arbitrary absolute path is refused', _refused('/etc/passwd'))
    check('a climb out of the runs directory is refused',
          _refused(str(runs_root / '..' / '..' / 'entity-bridge')))
    check('a non-existent handle is refused', _refused('this-handle-does-not-exist'))


def _refused(handle):
    try:
        discovery.parse_handle(handle)
        return False
    except (ValueError, OSError):
        return True


def case_source_documents_the_measurement():
    text = TARGET.read_text(encoding='utf-8')
    check('the wait constant carries the measurement that set it',
          '126.6' in text, 'the measured prompt lifetime is not recorded next to the constant')
    check('the cancel-detection change carries its measurement',
          'cancelled=false' in text,
          'the reason the check was widened is not recorded')


def case_ttl_is_accepted_by_the_real_validator():
    """The strongest form of the TTL check: ask the pinned validator itself.

    MEASURED (2026-09-30): a TTL of 360 was refused at run time with TTL_OUT_OF_RANGE,
    which cost the operator an elevation prompt. This compiles the probe but never
    elevates, never launches and skips the deadline check (`compile_only=True`), so it
    can answer the question offline. It is the check that would have prevented the burn.
    """
    sys.path.insert(0, str(ROOT / 'tools/game-executor'))
    import build_readonly_profile as readonly          # noqa: PLC0415
    output = ROOT / '.runtime/entity-create/toolchain-preflight/ttl-acceptance'
    try:
        readonly.prepare(output_root=output, ttl_seconds=discovery.PREPARATION_TTL_SECONDS,
                         compile_only=True)
    except ImportError as error:
        print('SKIP  the chosen TTL is accepted (toolchain unavailable: %s)' % error)
        return
    except Exception as error:
        check('the chosen TTL is accepted by the pinned validator', False,
              '%s: %s' % (type(error).__name__, error))
        return
    check('the chosen TTL is accepted by the pinned validator', True)


def case_pending_prompt_is_detected():
    """A pending elevation prompt jams the queue, so the run must refuse before launching."""
    check('no prompt reads as zero', discovery.pending_elevation_prompts(lambda: 0) == 0)
    check('one prompt reads as one', discovery.pending_elevation_prompts(lambda: 1) == 1)
    check('two prompts read as two', discovery.pending_elevation_prompts(lambda: 2) == 2)
    check('a numeric string is read as a number',
          discovery.pending_elevation_prompts(lambda: '3') == 3)
    check('an unreadable answer is reported as unknown, not as none',
          discovery.pending_elevation_prompts(lambda: (_ for _ in ()).throw(OSError())) == -1)

    def boom():
        raise OSError('cannot query')
    check('a failing query is unknown, not zero', discovery.pending_elevation_prompts(boom) == -1)

    text = TARGET.read_text(encoding='utf-8')
    # MEASURED: my first version of this check compared the refusal against the DEFINITION
    # of emit_launcher, which sits earlier in the file for unrelated reasons, so it failed
    # while the code was in fact correct. Compare against the CALL SITE instead.
    check('the refusal happens before the launcher is called',
          text.index('ELEVATION_ALREADY_PENDING') < text.index('exit_result = run_wrapper('),
          'the pending check must precede the launch call')
    check('the refusal says no prompt was raised by this run',
          'No prompt was raised by this run' in text)
    check('the query is real, not a stub',
          "'consent'" in text or 'Get-Process consent' in text)


def case_real_prompt_count_is_readable_offline():
    """The real query must run and answer, without raising and without launching anything."""
    count = discovery.pending_elevation_prompts()
    check('the live prompt query returns an integer', isinstance(count, int), repr(count))
    check('the live prompt query does not report unknown on this machine',
          count >= 0, str(count))
    print('INFO  elevation prompts currently on screen: %s' % count)


def case_pending_prompt_actually_blocks_the_launch(tmp: Path):
    """Behavioural: with a prompt pending, discover() must refuse and launch nothing.

    MEASURED: my first version of this suite only compared source ordering, so deleting the
    guard outright was NOT detected. This drives the real function with `prepare` stubbed
    (no compile, no elevation) and asserts the refusal happens and no launcher is written.
    """
    saved = {name: getattr(discovery, name) for name in ('pending_elevation_prompts',)}
    saved_prepare = discovery.readonly.prepare
    saved_wrapper = discovery.run_wrapper
    session = tmp / 'session.json'
    session.write_text(json.dumps({'pid': 1}), encoding='utf-8')
    output_root = ROOT / '.runtime/entity-create/toolchain-preflight/guard-test'
    try:
        # MEASURED: with only the count of 2 exercised, a guard that fired only for `>1`
        # passed unnoticed. One pending prompt already jams the queue, so test the value 1.
        for count in (1, 2):
            run_dir = tmp / ('blocked-launch-run-%d' % count)
            run_dir.mkdir(parents=True)
            launched = {'called': False}
            discovery.pending_elevation_prompts = lambda *a, _n=count, **k: _n
            discovery.readonly.prepare = lambda *a, _d=run_dir, **k: {'run': str(_d), 'hashes': {}}

            def must_not_launch(*a, **k):
                launched['called'] = True
                raise AssertionError('the launcher was invoked despite a pending prompt')
            discovery.run_wrapper = must_not_launch
            refusal = ''
            try:
                discovery.discover(session, output_root=output_root)
                check('a pending prompt refuses the run (count=%d)' % count, False,
                      'no error raised')
            except RuntimeError as error:
                refusal = str(error)
                check('a pending prompt refuses the run (count=%d)' % count,
                      'ELEVATION_ALREADY_PENDING' in refusal, refusal[:160])
            except AssertionError as error:
                check('a pending prompt refuses the run (count=%d)' % count, False, str(error))
            check('the launcher was never invoked (count=%d)' % count,
                  launched['called'] is False)
            check('no launcher script was written into the run (count=%d)' % count,
                  not (run_dir / 'launch-uac.ps1').exists())
            check('the refusal tells the operator what to do (count=%d)' % count,
                  'Dismiss the pending prompt' in refusal, refusal[-160:])
    finally:
        discovery.readonly.prepare = saved_prepare
        discovery.run_wrapper = saved_wrapper
        for name, value in saved.items():
            setattr(discovery, name, value)


def main() -> int:
    case_wait_covers_the_prompt()
    case_wait_is_long_enough_for_a_prompt()
    case_timeout_message_matches_the_constant()
    case_pending_prompt_is_detected()
    with tempfile.TemporaryDirectory() as temp:
        case_pending_prompt_actually_blocks_the_launch(Path(temp))
    case_real_prompt_count_is_readable_offline()
    case_ttl_is_accepted_by_the_real_validator()
    case_cancel_detection_actually_works()
    case_handle_resolver_refuses_escape(None)
    case_source_documents_the_measurement()
    print()
    if FAILURES:
        print('%d FAILED: %s' % (len(FAILURES), ', '.join(FAILURES)))
        return 1
    print('all checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
