#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search-corpora.py -- search EVERY sibling decompiled corpus, never just one.

WHY THIS EXISTS
---------------
This project has hit the same false negative five times: a claim says "X does
not exist" after grepping ONE decompiled corpus, while a *sibling* corpus --
an independent editor build with a re-randomised symbol space -- sat right
next to it, unsearched.  A negative on one corpus is not a negative on both.

Concretely there are (at least) two resolved corpora under
`.runtime/editor-catalog/`:

    resolved/              12,375 .cs   editor 7.0 build (SHA-256 D4B429A3..3841)
    resolved-565dda11/     12,955 .cs   editor 7.1 build (SHA-256 565dda11..678a)

Obfuscated type names do NOT overlap between them (only ~23 unobfuscated
framework names are shared), so a symbol present in one can be absent in the
other.  Searching one and reporting "absent" is a lie about the other.

WHAT IT DOES
------------
Given a pattern, it DISCOVERS every sibling corpus directory automatically
(any `<catalog-dir>/resolved*` that actually holds `.cs` files) and searches
all of them, reporting hits per corpus.  A caller cannot accidentally search
only one, because the corpus list is not a caller-supplied single path.

`--require-both` (default ON, disable with --no-require-both) turns "fewer than
two corpora were found" into a FAILURE (exit 2) rather than a silent pass --
so a deleted/moved sibling corpus is loud, not invisible.

OFFLINE ONLY.  Reads `.cs` files; touches no game, no editor, no network.

Run:
    PYTHONIOENCODING=utf-8 python tools/editor-catalog/search-corpora.py \\
        --pattern DeleteComponentForEditObj --require-both
Exit codes: 0 = searched every discovered corpus (>=2 under --require-both);
            2 = --require-both not satisfied (fewer than two corpora found);
            1 = usage / IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_DIR = REPO_ROOT / ".runtime/editor-catalog"

# A sibling corpus is a directory whose name starts with this and that holds
# at least one `.cs` file.  Keep it a prefix (not an exact set) so a new build
# (resolved-<hash>/) is picked up the day it is produced -- no code change.
CORPUS_PREFIX = "resolved"


def discover_corpora(catalog_dir, prefix=CORPUS_PREFIX):
    """Every `<catalog_dir>/<prefix>*` directory that holds at least one .cs.

    Returns a list of dicts sorted by name.  Discovery -- not a caller-supplied
    path -- is what makes 'search both' the default.
    """
    catalog_dir = Path(catalog_dir)
    found = []
    if not catalog_dir.is_dir():
        return found
    for entry in sorted(catalog_dir.iterdir()):
        if not entry.is_dir() or not entry.name.startswith(prefix):
            continue
        cs_count = sum(1 for _ in entry.glob("*.cs"))
        if cs_count == 0:
            continue
        found.append({"name": entry.name, "path": str(entry), "csCount": cs_count})
    return found


def read_build_identity(corpus_dir):
    """Best-effort build fingerprint for a corpus.

    Prefers the `.source.json` sidecar (`sourceSha256` / `profile` /
    `filesScanned`).  A corpus with no sidecar (the 7.0 `resolved/` tree has
    none) reports nulls -- absence is stated, never guessed.
    """
    ident = {"sourceSha256": None, "profile": None, "filesScanned": None}
    sidecar = Path(corpus_dir) / ".source.json"
    if not sidecar.is_file():
        return ident
    try:
        with open(sidecar, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return ident
    for key in ident:
        value = data.get(key)
        if value is not None:
            ident[key] = value
    return ident


def compile_pattern(pattern, fixed):
    """Compile the query.  --fixed escapes so a literal is a literal."""
    if fixed:
        pattern = re.escape(pattern)
    return re.compile(pattern)


def search_corpus(corpus, regex, show_lines=0):
    """Count matches (and matched files) in one corpus.  Read-only.

    `corpus` is a discover_corpora() dict; the result annotates it with the
    match counts and (optionally) up to `show_lines` sample matching lines.
    """
    total = 0
    files_matched = 0
    samples = []
    for cs in sorted(Path(corpus["path"]).glob("*.cs")):
        try:
            text = cs.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = 0
        for lineno, line in enumerate(text.splitlines(), 1):
            n = len(regex.findall(line))
            if n:
                hits += n
                if len(samples) < show_lines:
                    samples.append({"file": cs.name, "line": lineno,
                                    "text": line.strip()[:200]})
        if hits:
            files_matched += 1
            total += hits
    result = dict(corpus)
    result["matchCount"] = total
    result["filesMatched"] = files_matched
    result["identity"] = read_build_identity(corpus["path"])
    if show_lines:
        result["samples"] = samples
    return result


def search_corpora(corpora, regex, show_lines=0):
    """Search every corpus and return the per-corpus results, in corpus order."""
    return [search_corpus(c, regex, show_lines=show_lines) for c in corpora]


def verdict(results, require_both):
    """Decide exit status.  Returns (code, message).

    A pass means every discovered corpus was searched.  Under --require-both a
    pass additionally needs at least two corpora -- otherwise a caller silently
    searching a lone corpus looks like success.
    """
    if require_both and len(results) < 2:
        return 2, ("REFUSED: --require-both but only %d corpus/corpora found "
                   "(%s); a negative on one corpus is not a negative on all"
                   % (len(results), ", ".join(r["name"] for r in results) or "none"))
    return 0, None


def format_report(results, pattern, message=None):
    lines = ["search-corpora: pattern=%r" % pattern,
             "corpora searched: %d" % len(results)]
    for r in results:
        ident = r["identity"]
        sha = (ident["sourceSha256"] or "<no source.json>")
        if sha != "<no source.json>":
            sha = sha[:12] + ".."
        lines.append("  [%s] files=%d csFiles=%d matches=%d matchedFiles=%d build=%s"
                     % (r["name"], r["csCount"], r["csCount"],
                        r["matchCount"], r["filesMatched"], sha))
        for s in r.get("samples", []):
            lines.append("      %s:%d: %s" % (s["file"], s["line"], s["text"]))
    if message:
        lines.append(message)
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pattern", required=True, help="the regex (or --fixed literal) to search")
    ap.add_argument("--catalog-dir", default=str(DEFAULT_CATALOG_DIR),
                    help="directory holding the resolved* corpora")
    ap.add_argument("--fixed", action="store_true", help="treat --pattern as a literal string")
    ap.add_argument("--show-lines", type=int, default=0,
                    help="emit up to N sample matching lines per corpus")
    ap.add_argument("--require-both", dest="require_both", action="store_true", default=True,
                    help="FAIL if fewer than two corpora are found (default: on)")
    ap.add_argument("--no-require-both", dest="require_both", action="store_false",
                    help="disable the two-corpus requirement (debugging only)")
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = ap.parse_args(argv)

    corpora = discover_corpora(args.catalog_dir)
    try:
        regex = compile_pattern(args.pattern, args.fixed)
    except re.error as exc:
        sys.stderr.write("search-corpora: bad pattern: %s\n" % exc)
        return 1

    results = search_corpora(corpora, regex, show_lines=args.show_lines)
    code, message = verdict(results, args.require_both)

    if args.json:
        json.dump({"pattern": args.pattern, "corpora": results,
                   "message": message, "exitCode": code},
                  sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_report(results, args.pattern, message) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
