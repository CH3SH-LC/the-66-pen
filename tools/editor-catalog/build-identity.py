#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Frozen identity check: is the CENSUS assembly the same build as the CORPUS?

Why this exists
---------------
The editor-bridge relies on symbol names that were mined from a *static* census
of one specific `BeyondEditor.dll` (sha256 recorded in the census JSON).  All
downstream artefacts -- the annotated 7.1 decompiled corpus, the node graph
adapter, every 11-char obfuscated symbol in EditorBindingProfile -- are only
valid for **that exact build**.  If the installed `BeyondEditor.dll` is ever
replaced (game patch), the census stops describing the live assembly and every
mined symbol silently becomes a lie.  This script makes that divergence
*loud* instead of silent.

What it compares (offline, read-only, no game / no editor / no network)
-----------------------------------------------------------------------
* The census JSON records `sourceSha256` -- the hash of the DLL it was read from.
* A decompiled corpus directory (e.g. `.../strings/annotated-7.1`) is a tree of
  `Namespace.ClassName.cs` files (`.source.json` sits alongside it).  Its
  namespaces are derived from the file names; some corpora also record their own
  `sourceSha256` inside `.source.json`.

  A corpus file name mangles IL type punctuation: generic arity `` `3 `` and
  nesting `+` both become `_` on disk.  That only touches the *type* segment,
  never the namespace, so namespace extraction is unaffected.

Verdict rule
------------
    SAME-BUILD      iff census and corpus `sourceSha256` are both present and
                        equal (byte-level proof), OR -- when a side records no
                        sha, so bytes cannot be compared -- the namespace
                        intersection covers >= --threshold of the smaller side
                        (default 0.95) and is at least --min-shared namespaces
                        (default 20).
    DIFFERENT-BUILD if the two sha256 disagree, or the namespace fallback is not
                    met, or the corpus is empty (fail closed).

A byte-different DLL is DIFFERENT-BUILD even if most namespaces survive: a
patched assembly can invalidate mined symbols without removing namespaces.

ONE-LINE RULE for a future agent on a DIFFERENT-BUILD verdict:
    When the verdict is DIFFERENT-BUILD, the census / corpus / mined symbols do
    NOT describe the live editor -- re-derive every symbol from the current
    `BeyondEditor.dll` before any bridge dispatch; reuse nothing.

Run:
    PYTHONIOENCODING=utf-8 python tools/editor-catalog/build-identity.py \\
        --census .runtime/scratch/editor-method-census.json \\
        --corpus .runtime/verification/update-repair-20260925/strings/annotated-7.1
Exit code 0 = SAME-BUILD, 2 = DIFFERENT-BUILD, 1 = usage/IO error.
"""
import argparse
import json
import sys
from pathlib import Path

VERDICT_SAME = "SAME-BUILD"
VERDICT_DIFFERENT = "DIFFERENT-BUILD"

DEFAULT_THRESHOLD = 0.95
DEFAULT_MIN_SHARED = 20

# Reasons, surfaced so a bare "DIFFERENT-BUILD" is never opaque.
REASON_SHA_MATCH = "sha256-match"
REASON_NAMESPACE_COVERAGE = "namespace-coverage"
REASON_SHA_MISMATCH = "sha256-mismatch"
REASON_LOW_OVERLAP = "low-namespace-overlap"
REASON_NO_CORPUS_NAMESPACES = "no-corpus-namespaces"
REASON_NO_CENSUS_NAMESPACES = "no-census-namespaces"


def load_census(path):
    """Parse the census JSON.  Raises on unreadable / malformed input."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def census_sha256(census):
    """The recorded sha256 of the DLL the census was read from, or None."""
    value = census.get("sourceSha256")
    return value if value else None


def census_type_count(census):
    """Type-def rows.  Prefer the explicit `typeCount`, else len(types)."""
    if isinstance(census.get("typeCount"), int):
        return census["typeCount"]
    return len(census.get("types") or [])


def census_namespaces(census):
    """Distinct namespaces of the census type-def rows ('' = global namespace)."""
    namespaces = set()
    for t in census.get("types") or []:
        ns = t.get("namespace")
        namespaces.add(ns if ns is not None else "")
    return namespaces


def corpus_namespaces(corpus_dir):
    """Distinct namespaces derived from `*.cs` file names in a corpus dir.

    A file `Ns.Sub.Class.cs` -> namespace `Ns.Sub`; a bare `Class.cs` -> `''`.
    """
    namespaces = set()
    for entry in Path(corpus_dir).glob("*.cs"):
        stem = entry.name[:-3]  # strip ".cs"
        if "." in stem:
            namespaces.add(stem.rsplit(".", 1)[0])
        else:
            namespaces.add("")
    return namespaces


def corpus_source_sha256(corpus_dir):
    """Read `sourceSha256` from a sibling `.source.json`, or None if absent."""
    src = Path(corpus_dir) / ".source.json"
    if not src.is_file():
        return None
    try:
        with open(src, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    value = data.get("sourceSha256")
    return value if value else None


def classify(census_ns, corpus_ns, census_sha, corpus_sha,
             threshold=DEFAULT_THRESHOLD, min_shared=DEFAULT_MIN_SHARED):
    """Pure decision function -> report dict.  No I/O, so it is easy to test."""
    intersection = census_ns & corpus_ns
    census_count = len(census_ns)
    corpus_count = len(corpus_ns)
    min_side = min(census_count, corpus_count)
    coverage = (len(intersection) / min_side) if min_side else 0.0
    sha_match = bool(census_sha) and bool(corpus_sha) and census_sha == corpus_sha

    # Byte-level sha256 is definitive in BOTH directions: equal -> same build,
    # different -> different build (a patched DLL invalidates mined symbols even
    # if most namespaces survive).  The namespace heuristic is only the fallback
    # for when one side records no sha at all.
    if sha_match:
        verdict, reason = VERDICT_SAME, REASON_SHA_MATCH
    elif census_sha and corpus_sha:
        verdict, reason = VERDICT_DIFFERENT, REASON_SHA_MISMATCH
    elif census_count == 0:
        verdict, reason = VERDICT_DIFFERENT, REASON_NO_CENSUS_NAMESPACES
    elif corpus_count == 0:
        verdict, reason = VERDICT_DIFFERENT, REASON_NO_CORPUS_NAMESPACES
    elif coverage >= threshold and len(intersection) >= min_shared:
        verdict, reason = VERDICT_SAME, REASON_NAMESPACE_COVERAGE
    else:
        verdict, reason = VERDICT_DIFFERENT, REASON_LOW_OVERLAP

    return {
        "verdict": verdict,
        "reason": reason,
        "sourceSha256": census_sha,
        "corpusSourceSha256": corpus_sha,
        "shaMatch": sha_match,
        "typeCount": None,  # filled by analyze() when a census is loaded
        "censusNamespaceCount": census_count,
        "corpusNamespaceCount": corpus_count,
        "namespaceIntersection": len(intersection),
        "coverage": coverage,
        "threshold": threshold,
        "minShared": min_shared,
    }


def analyze(census_path, corpus_dir, threshold=DEFAULT_THRESHOLD,
            min_shared=DEFAULT_MIN_SHARED):
    """End-to-end: load both sides and classify.  Read-only."""
    census = load_census(census_path)
    report = classify(
        census_namespaces(census),
        corpus_namespaces(corpus_dir),
        census_sha256(census),
        corpus_source_sha256(corpus_dir),
        threshold=threshold,
        min_shared=min_shared,
    )
    report["typeCount"] = census_type_count(census)
    report["censusPath"] = str(census_path)
    report["corpusPath"] = str(corpus_dir)
    return report


def format_report(report):
    lines = [
        "build-identity check",
        "  census            : %s" % report["censusPath"],
        "  corpus            : %s" % report["corpusPath"],
        "  sourceSha256      : %s" % (report["sourceSha256"] or "<none>"),
        "  corpusSourceSha256: %s" % (report["corpusSourceSha256"] or "<none>"),
        "  shaMatch          : %s" % report["shaMatch"],
        "  typeCount         : %s" % report["typeCount"],
        "  censusNamespaces  : %d" % report["censusNamespaceCount"],
        "  corpusNamespaces  : %d" % report["corpusNamespaceCount"],
        "  intersection      : %d" % report["namespaceIntersection"],
        "  coverage(min side): %.4f" % report["coverage"],
        "  VERDICT           : %s (%s)" % (report["verdict"], report["reason"]),
    ]
    if report["verdict"] == VERDICT_DIFFERENT:
        lines.append(
            "  RULE: symbols do NOT describe the live editor -- re-derive from "
            "the current BeyondEditor.dll; reuse nothing.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--census", required=True, help="path to the census JSON")
    ap.add_argument("--corpus", required=True, help="path to the corpus dir")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help="min coverage of the smaller side (default 0.95)")
    ap.add_argument("--min-shared", type=int, default=DEFAULT_MIN_SHARED,
                    help="min intersection size for a coverage verdict (default 20)")
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = ap.parse_args(argv)

    try:
        report = analyze(args.census, args.corpus,
                         threshold=args.threshold, min_shared=args.min_shared)
    except (OSError, ValueError) as exc:
        sys.stderr.write("build-identity: %s\n" % exc)
        return 1

    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_report(report) + "\n")
    return 0 if report["verdict"] == VERDICT_SAME else 2


if __name__ == "__main__":
    sys.exit(main())
