"""A concrete ``SaveDiffVerifier`` for ``backend/cleanup_service.py`` (W10 / R11).

WHY THIS FILE EXISTS
--------------------
``backend/cleanup_service.py`` froze the DS-05 seam as a bare Protocol::

    class SaveDiffVerifier(Protocol):
        def verify_cleanup_save(self, manifest: dict) -> Any: ...

``CleanupService.__init__`` accepts ``save_diff`` and ``_cleanup_save_diff`` refuses
to judge anything when it is ``None`` (``SAVE_DIFF_VERIFIER_UNAVAILABLE``).  The
offline CLI (``cleanup_service.main``) built its service without one, so
``cleanup-save-diff`` could not leave ``blocked`` for any reason other than
"no verifier is wired".  This module implements the Protocol by **delegating** to
the one producer that already exists and was delivered for exactly this job:
``backend/save_verification.py`` (DS-05 / T09) -- ``verify_saved_case(manifest)``.

WHAT IT CONSUMES
----------------
It consumes the **actual manifest** that the save path produces -- the
``checks/manifest.schema.json``-shaped document written by
``backend/save_manifest.py`` (W08) and handed in verbatim, as an object or as the
path of the file on disk.  The adapter adds no key to that document and reads no
key of its own invention off the *cleanup* manifest; the only thing it does with
the cleanup evidence manifest is a single identity guard (the save case must be
about the same level the cleanup ran in).  In particular it does **not** invent a
``saveManifest`` / ``saveCaseManifest`` / ``saveManifestPath`` lookup on the plan
manifest, and it does **not** require the save case to declare a ``removedIds``
attribution before it will answer -- those are the caller's materials, and a
verifier that refused without them would report "cannot judge" for a case DS-05
can judge perfectly well.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
* It never re-implements an axis.  The DS-05 report is returned **unchanged**; the
  four axes (saveInvocation / savedContent / allowedDelta / unrelatedUnchanged) are
  recomputed from bytes by that module, never by this one.
* It never sets ``layer``.  DS-05's report has no such field, and
  ``cleanup_service.adapt_save_verification`` derives ``layer`` from whether every
  bound ``{path, sha256}`` the caller supplied really resolves -- so a fixture whose
  paths are made up can never reach ``pass``, and that rule is not touched here.
* It never edits the save case to make it judgeable (no writing of
  ``entityDelta.removedIds``, no suppression of named deltas).  root46 therefore
  stays a named ``blocked`` delta all the way through, exactly as DS-05 reports it.

REFUSALS (all return ``cleanup_service.VerificationUnavailable``)
-----------------------------------------------------------------
``CLEANUP_MANIFEST_SHAPE_UNKNOWN``  the cleanup evidence manifest is not an object
``SAVE_MANIFEST_MISSING``           no DS-05 save-case manifest was supplied
``SAVE_MANIFEST_UNREADABLE``        the supplied path is not a readable JSON object
``SAVE_MANIFEST_WRONG_LEVEL``       the save case is about a different level
``SAVE_MANIFEST_SHAPE_UNKNOWN``     the save case binds no gilBefore/gilAfter pair

The ``VerificationUnavailable`` class object must be the one the calling
``cleanup_service`` module will ``isinstance`` against.  That module is importable
both as ``backend.cleanup_service`` and as ``__main__`` (the CLI is run as a
script), so the class is resolved from ``sys.modules`` at call time and the CLI
injects its own class explicitly through the ``unavailable`` argument.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The module the seam class must be taken from, in resolution order.
CLEANUP_MODULE_NAMES = ("backend.cleanup_service", "cleanup_service")

SAVE_DIFF_ADAPTER_PATH = ROOT / "backend/cleanup_save_diff_adapter.py"

#: The two bound files DS-05's own ``_entry(manifest, 'files')`` reaches for first;
#: a case that binds neither is not a save case this module can hand to it.
REQUIRED_BOUND_FILES = ("gilBefore", "gilAfter")


def _find_live_module(names, attribute):
    for name in names:
        module = sys.modules.get(name)
        if module is not None and hasattr(module, attribute):
            return module
    return None


def _load_by_path(module_name, path):
    """Load a module by path (a directory name may contain a hyphen)."""
    path = Path(path)
    if not path.is_file():
        raise RuntimeError("SAVE_DIFF_ADAPTER_SOURCE_MISSING: %s" % path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("SAVE_DIFF_ADAPTER_SOURCE_UNLOADABLE: %s" % path)
    module = importlib.util.module_from_spec(spec)
    # Register before exec_module: the module uses ``from __future__ import
    # annotations``, and ``@dataclass`` resolves those strings through
    # ``sys.modules[cls.__module__]`` -- which does not exist for a by-path load.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


def load_save_verification():
    """The already-imported ``backend/save_verification.py``, or a by-path copy.

    Never re-implements it: when the module is not importable as a package member
    (the CLI is run as a script), the file is loaded by path so the *same source*
    is used.
    """
    module = _find_live_module(("backend.save_verification", "save_verification"),
                               "verify_saved_case")
    if module is not None:
        return module
    try:
        from backend import save_verification as module        # noqa: F401
        return module
    except ImportError:
        return _load_by_path("_cleanup_save_verification_reused",
                             ROOT / "backend/save_verification.py")


class ExistingSaveVerifier:
    """``cleanup_service.SaveDiffVerifier`` backed by the existing DS-05 verifier.

    ``case`` is the save-case (W08) manifest: either the parsed document, or a path
    to it (resolved once, lazily, so a missing file is a named refusal rather than a
    construction-time crash).  Both ``direct`` (``verify_saved_case(case)``) and
    ``via`` (``orchestrate_s12`` -> this adapter) therefore judge the *same*
    document with the *same* code; the adapter adds only an identity guard.
    """

    def __init__(self, *, case=None, verify=None, reader=None, runner=None,
                 timeout=300.0, out_dir=None, unavailable=None):
        self._case = case
        self._verify = verify
        self._reader = reader
        self._runner = runner
        self._timeout = timeout
        self._out_dir = Path(out_dir) if out_dir is not None else None
        self._unavailable_class = unavailable

    # -- refusals ----------------------------------------------------------- #

    def _unavailable(self, code, detail):
        cls = self._unavailable_class
        if cls is None:
            module = _find_live_module(CLEANUP_MODULE_NAMES, "VerificationUnavailable")
            if module is None:
                raise RuntimeError(
                    "CLEANUP_SERVICE_SEAM_MISSING: no loaded cleanup_service module exposes "
                    "VerificationUnavailable, and none was injected; pass unavailable=")
            cls = module.VerificationUnavailable
        return cls(code, detail)

    def _verify_callable(self):
        if self._verify is not None:
            return self._verify
        return load_save_verification().verify_saved_case

    # -- manifest resolution ------------------------------------------------ #

    def _case_manifest(self):
        """``(case | None, code, why)`` -- never guesses and never synthesises one."""
        value = self._case
        if value is None:
            return None, "SAVE_MANIFEST_MISSING", (
                "no DS-05 save-case manifest was supplied to the cleanup save verifier: "
                "the save that follows a cleanup cannot be judged without the case the "
                "save path produced (backend/save_manifest.py).  Pass it as "
                "--save-case-manifest <manifest.json>.")
        if isinstance(value, (str, Path)):
            path = Path(value)
            if not path.is_file():
                return None, "SAVE_MANIFEST_UNREADABLE", (
                    "the save-case manifest is not on disk: %s" % path)
            try:
                value = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as error:
                return None, "SAVE_MANIFEST_UNREADABLE", (
                    "the save-case manifest is unreadable: %s: %s"
                    % (type(error).__name__, error))
        if not isinstance(value, dict):
            return None, "SAVE_MANIFEST_UNREADABLE", (
                "the save-case manifest is not a JSON object")
        return value, None, None

    # -- the Protocol -------------------------------------------------------- #

    def verify_cleanup_save(self, manifest):
        cleanup_manifest = manifest if isinstance(manifest, dict) else None
        if cleanup_manifest is None:
            return self._unavailable("CLEANUP_MANIFEST_SHAPE_UNKNOWN",
                                     "the cleanup evidence manifest is not an object")

        case, code, why = self._case_manifest()
        if case is None:
            return self._unavailable(code, why)

        # (1) identity: a save case about another level is not *this* cleanup's save.
        case_level = case.get("levelId")
        cleanup_level = cleanup_manifest.get("levelId")
        if case_level is None or cleanup_level is None \
                or str(case_level) != str(cleanup_level):
            return self._unavailable("SAVE_MANIFEST_WRONG_LEVEL",
                                     {"caseLevelId": case_level,
                                      "cleanupLevelId": cleanup_level,
                                      "rule": "a save case for another level is not evidence "
                                              "about the level this cleanup ran in"})

        # (2) shape: DS-05 judges the bound gil pair; a case that binds neither is
        #     not the document this adapter was handed to consume.
        files = case.get("files")
        if not isinstance(files, dict) or any(k not in files for k in REQUIRED_BOUND_FILES):
            return self._unavailable("SAVE_MANIFEST_SHAPE_UNKNOWN",
                                     {"rule": "the save case must bind files.gilBefore and "
                                              "files.gilAfter; DS-05 judges those bytes"})

        verify = self._verify_callable()
        kwargs = {}
        if self._reader is not None:
            kwargs["reader"] = self._reader
        if self._runner is not None:
            kwargs["runner"] = self._runner
        if self._timeout is not None:
            kwargs["timeout"] = self._timeout
        if self._out_dir is not None:
            kwargs["out_dir"] = self._out_dir
        # The DS-05 report, unchanged.  ``cleanup_service`` normalises it with
        # ``adapt_save_verification``, which carries every stage verdict over as-is and
        # derives ``layer`` from the caller's own binding -- not from anything here.
        return verify(case, **kwargs)
