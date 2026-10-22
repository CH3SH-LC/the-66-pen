#!/usr/bin/env python3
"""symbol-map-71.py -- offline 7.0 -> 7.1 editor symbol lookup.

WHY THIS EXISTS
---------------
Symbols (type / method / field names) were re-randomised between the 7.0 build
and the installed 7.1 build. Every piece of KNOWLEDGE this project holds about
the editor's classes is recorded under the 7.0 (legacy) names. A curated
legacy -> actual map already exists at:

    .runtime/verification/update-repair-20260925/adapter-port/merged-symbols-7.1.json

It is a flat JSON object ``{ "<7.0 name>": "<7.1 name>" }``. It was assembled
from the candidate pipelines in the same directory and then consumed by
``integrate_profile.py`` (which resolves each *value* against the 7.1 PE
metadata and fails closed on anything unresolved). See
``docs/research/reverse-eng-20261010/SYMBOL-MAP-71.md`` for provenance.

WHAT IT DOES
------------
Given a 7.0 symbol string, :meth:`SymbolMap71.lookup` returns its 7.1
counterpart -- or ``status="unknown"`` with ``new=None``.

    >>> m = SymbolMap71({"Ns.Type": "Ns2.Type2"})
    >>> m.lookup("Ns.Type")["new"]
    'Ns2.Type2'
    >>> m.lookup("Type")["status"]          # substring, NOT a key -> refused
    'unknown'

EXACT MATCH ONLY.  The map has no structure beyond ``str -> str``: some keys
are type full names (``Namespace.Type``), the rest are bare member leaf names
(``doThing``). There is no ``Type.Member`` scheme, so a query is answered only
when the *whole string* is a key. A prefix, suffix or substring of a key is
NEVER returned as an answer -- :meth:`near_misses` reports such keys for a
human to inspect, but they are informational and carry no mapping.

OFFLINE ONLY. This module reads one JSON file and touches nothing else -- no
game, no editor, no binary, no network.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAP = (
    REPO_ROOT
    / ".runtime/verification/update-repair-20260925/adapter-port/merged-symbols-7.1.json"
)

STATUS_MAPPED = "mapped"
STATUS_UNKNOWN = "unknown"


class SymbolMapError(ValueError):
    """Raised when the map file (or a query) is malformed."""


class SymbolMap71:
    """A read-only, exact-match view over a 7.0 -> 7.1 symbol map."""

    def __init__(self, mapping):
        if not isinstance(mapping, dict):
            raise SymbolMapError(
                "symbol map must be a JSON object, got %s" % type(mapping).__name__
            )
        for key, value in mapping.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise SymbolMapError(
                    "symbol map entries must be str -> str, got %r -> %r"
                    % (key, value)
                )
        # Defensive copy: callers cannot mutate the map underneath us.
        self._map = dict(mapping)

    # -- construction ----------------------------------------------------
    @classmethod
    def load(cls, path=None):
        """Load a map from *path* (default: the curated 7.1 map)."""
        target = Path(path) if path is not None else DEFAULT_MAP
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SymbolMapError("symbol map not found: %s" % target) from exc
        except json.JSONDecodeError as exc:
            raise SymbolMapError("symbol map is not valid JSON: %s" % exc) from exc
        return cls(raw)

    # -- introspection ---------------------------------------------------
    def __len__(self):
        return len(self._map)

    def __contains__(self, symbol):
        return symbol in self._map

    def keys(self):
        return sorted(self._map)

    def near_misses(self, old):
        """Keys that share a *substring* with *old*, sorted. INFORMATIONAL.

        These are never valid answers -- they exist only so a caller refusing
        an unknown symbol can show the closest things that did not match.
        """
        if not isinstance(old, str) or not old:
            return []
        return sorted(
            key for key in self._map if key != old and (old in key or key in old)
        )

    # -- lookup ----------------------------------------------------------
    def lookup(self, old):
        """Resolve one 7.0 symbol string. Exact match or ``unknown``.

        Returns a dict:
          old        -- the query, unchanged
          status     -- ``"mapped"`` or ``"unknown"``
          new        -- the 7.1 name, or ``None`` when unknown
          identity   -- True when the map maps a name to itself
          nearMisses -- substring-similar keys (never an answer); [] when mapped

        Raises SymbolMapError for a non-string query.
        """
        if not isinstance(old, str):
            raise SymbolMapError(
                "symbol must be a string, got %s" % type(old).__name__
            )
        if old in self._map:
            new = self._map[old]
            return {
                "old": old,
                "status": STATUS_MAPPED,
                "new": new,
                "identity": new == old,
                "nearMisses": [],
            }
        return {
            "old": old,
            "status": STATUS_UNKNOWN,
            "new": None,
            "identity": False,
            "nearMisses": self.near_misses(old),
        }

    def lookup_type(self, old_full_name):
        """Alias of :meth:`lookup` -- a type is looked up by its full name."""
        return self.lookup(old_full_name)

    def attempt_member_lookup(self, owner, member):
        """Resolve a method/field by ``(owner, member)`` -- still EXACT.

        The map stores members by their bare leaf name, so the two candidate
        keys are tried verbatim, in order:

          1. ``"<owner>.<member>"`` -- matches iff the map literally holds that
             qualified string (e.g. a type full name, or a future qualified
             member key);
          2. ``"<member>"`` -- the bare leaf.

        Both are exact lookups; nothing is derived or guessed from *owner*.
        The result carries ``owner`` so the caller can show which form (if any)
        answered.
        """
        if not isinstance(owner, str):
            raise SymbolMapError("owner must be a string, got %s" % type(owner).__name__)
        qualified = owner + "." + member
        for candidate in (qualified, member):
            if candidate in self._map:
                result = self.lookup(candidate)
                result["owner"] = owner
                result["matchedForm"] = candidate
                return result
        result = self.lookup(member)
        result["owner"] = owner
        result["matchedForm"] = None
        return result

    def lookup_many(self, olds):
        return [self.lookup(old) for old in olds]


def _format(result, as_json):
    if as_json:
        return json.dumps(result, ensure_ascii=False, sort_keys=True)
    if result["status"] == STATUS_MAPPED:
        suffix = "  (identity)" if result.get("identity") else ""
        return "%s  ->  %s%s" % (result["old"], result["new"], suffix)
    text = "%s  ->  UNKNOWN" % result["old"]
    names = result.get("nearMisses") or []
    if names:
        text += "  (no exact key; %d substring-similar key(s) refused: %s)" % (
            len(names),
            ", ".join(names[:5]) + ("..." if len(names) > 5 else ""),
        )
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Resolve 7.0 editor symbols to their 7.1 counterparts (exact match only)."
    )
    parser.add_argument("symbols", nargs="+", help="7.0 symbol name(s) to resolve")
    parser.add_argument("--map", dest="map_path", default=None, help="override the map JSON path")
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    args = parser.parse_args(argv)

    try:
        symbol_map = SymbolMap71.load(args.map_path)
    except SymbolMapError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    results = symbol_map.lookup_many(args.symbols)
    if args.json:
        print(
            json.dumps(
                {"mapPath": str(args.map_path or DEFAULT_MAP), "mapSize": len(symbol_map), "results": results},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for result in results:
            print(_format(result, as_json=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
