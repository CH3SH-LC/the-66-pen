#!/usr/bin/env python3
"""Shared guards for the offline editor-catalog resource pipeline.

Stdlib only, and no dependency on the other scripts in this directory. Every
stage of the pipeline fails closed on the same conditions:

  * source and output trees that overlap
  * output / index / sidecar files that already exist (never overwrite)
  * decoder provenance that is missing, malformed or from another tool
  * decoded samples that are stale, tampered, mixed-source or failed

Scope note: this module validates internal file integrity for this offline
pipeline only. It says nothing about the live game or the editor, and a pass
here is not a claim of official or semantically verified status for any field
interpretation produced by the scripts that use it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Iterator

# Bumped whenever the provenance/manifest record layout changes incompatibly.
SCHEMA_VERSION = 1

DECODER_TOOL = "decode-mihoyobin.py"
PROVENANCE_NAME = "_provenance.json"

READ_CHUNK = 1 << 20


class CatalogError(Exception):
    """Fatal pipeline condition; callers turn this into a nonzero exit."""


def resolve(path) -> Path:
    return Path(path).expanduser().resolve()


def is_within(child, parent) -> bool:
    c, p = resolve(child), resolve(parent)
    return c == p or p in c.parents


def ensure_no_overlap(a, b, label_a: str = "source", label_b: str = "output") -> None:
    """Refuse when either tree contains the other, or they are the same path."""
    pa, pb = resolve(a), resolve(b)
    if is_within(pa, pb) or is_within(pb, pa):
        raise CatalogError(f"{label_a} and {label_b} overlap: {pa} <-> {pb}")


def ensure_absent(path, label: str = "output") -> Path:
    """Return ``path`` resolved, refusing to continue if it already exists."""
    p = resolve(path)
    if p.exists():
        raise CatalogError(f"{label} already exists, refusing to overwrite: {p}")
    return p


def ensure_fresh_dir(path, label: str = "output directory") -> Path:
    """Create ``path``; an existing directory is allowed only if it is empty."""
    p = resolve(path)
    if p.exists():
        if not p.is_dir():
            raise CatalogError(f"{label} exists and is not a directory: {p}")
        if any(p.iterdir()):
            raise CatalogError(f"{label} exists and is not empty: {p}")
    else:
        p.mkdir(parents=True, exist_ok=True)
    return p


def exclusive_write_text(path, text: str, label: str = "output") -> Path:
    p = ensure_absent(path, label)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "x", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return p


def exclusive_write_bytes(path, data: bytes, label: str = "output") -> Path:
    p = ensure_absent(path, label)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "xb") as fh:
        fh.write(data)
    return p


def iter_file_chunks(path, chunk_size: int = READ_CHUNK) -> Iterator[bytes]:
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk_size)
            if not block:
                return
            yield block


def sha256_file(path, chunk_size: int = READ_CHUNK) -> str:
    h = hashlib.sha256()
    for block in iter_file_chunks(path, chunk_size):
        h.update(block)
    return h.hexdigest()


def source_set_id(pairs: Iterable[tuple[str, str]]) -> str:
    """Stable content id for an input set.

    ``pairs`` is an iterable of ``(relative_path, digest)``. The id depends only
    on the relative paths and their digests, so it is stable across runs and
    machines, and changes whenever any member's content changes.
    """
    h = hashlib.sha256()
    norm = sorted(((str(r).replace("\\", "/"), str(d)) for r, d in pairs))
    for rel, digest in norm:
        h.update(rel.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n")
    return h.hexdigest()



def validate_provenance(prov: dict) -> None:
    """Check the complete source set before selecting a consumer subset."""
    if prov.get("schema_version") != SCHEMA_VERSION or not prov.get("source_root"):
        raise CatalogError("unsupported or missing provenance schema/source root")
    records = prov.get("files")
    if not isinstance(records, list) or not records:
        raise CatalogError("provenance has no decoded file records")
    rels, outputs, pairs = set(), set(), []
    for rec in records:
        if not isinstance(rec, dict):
            raise CatalogError("malformed provenance record")
        rel, digest = rec.get("source_relative_path"), rec.get("source_sha256")
        if not isinstance(rel, str) or not rel or rel in rels:
            raise CatalogError("missing/duplicate provenance source_relative_path")
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise CatalogError("provenance source_relative_path escapes source root")
        rels.add(rel)
        if rec.get("source_set_sha256") != prov.get("source_set_sha256"):
            raise CatalogError("mixed source-set id in provenance")
        if not rec.get("ok") or not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise CatalogError(f"failed or unhashed provenance input: {rel}")
        if resolve(rec.get("source_path", "")) != resolve(Path(prov["source_root"]) / rel):
            raise CatalogError(f"provenance source path mismatch: {rel}")
        out = rec.get("output")
        if out:
            if Path(out).name != out or out in outputs:
                raise CatalogError("invalid/duplicate provenance output filename")
            outputs.add(out)
        pairs.append((rel, digest))
    if source_set_id(pairs) != prov.get("source_set_sha256"):
        raise CatalogError("provenance source-set fingerprint mismatch")


def check_output_paths(paths, decoded_dir, prov: dict) -> None:
    """Preflight the entire output bundle before creating any of its files."""
    seen = []
    for path in paths:
        if path is None:
            continue
        p = ensure_absent(path)
        ensure_no_overlap(decoded_dir, p, "decoded inputs", "output")
        ensure_no_overlap(prov["source_root"], p, "resource inputs", "output")
        for prior in seen:
            ensure_no_overlap(prior, p, "output", "other output")
        seen.append(p)


def load_provenance(decoded_dir) -> dict:
    """Load and structurally check the decoder's provenance manifest."""
    root = resolve(decoded_dir)
    if not root.is_dir():
        raise CatalogError(f"decoded directory missing: {root}")
    prov_path = root / PROVENANCE_NAME
    if not prov_path.is_file():
        raise CatalogError(
            f"decoder provenance missing: {prov_path}; run {DECODER_TOOL} --out first"
        )
    try:
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"decoder provenance is malformed: {prov_path}: {exc}") from exc
    if not isinstance(prov, dict):
        raise CatalogError(f"decoder provenance is not a JSON object: {prov_path}")
    if prov.get("tool") != DECODER_TOOL:
        raise CatalogError(f"provenance is not from {DECODER_TOOL}: {prov.get('tool')!r}")
    if prov.get("schema_version") != SCHEMA_VERSION:
        raise CatalogError(
            f"unsupported provenance schema_version: {prov.get('schema_version')!r}"
        )
    if not isinstance(prov.get("source_set_sha256"), str) or not prov["source_set_sha256"]:
        raise CatalogError("provenance has no source_set_sha256")
    if not isinstance(prov.get("files"), list) or not prov["files"]:
        raise CatalogError("provenance has no decoded file records")
    validate_provenance(prov)
    return prov


def select_decoded_entries(
    prov: dict,
    decoded_dir,
    predicate,
    required_label: str = "input",
    verify_source: bool = True,
) -> list[dict]:
    """Select provenance records matching ``predicate`` and verify their integrity.

    Only the records the caller actually needs must be present -- the installed
    dataset can be far larger than any single consumer requires. Each selected
    record is checked for a consistent source-set id, a successful decode, and
    an on-disk output whose sha256 matches the recorded one. When
    ``verify_source`` is set, the original source file must also still exist and
    hash the same, which is what turns a game update into a loud stale error
    instead of a silently wrong catalogue.
    """
    root = resolve(decoded_dir)
    sid = prov["source_set_sha256"]
    selected = [r for r in prov["files"] if isinstance(r, dict) and predicate(r)]
    if not selected:
        raise CatalogError(f"decoded provenance has no {required_label} records under {root}")
    for rec in selected:
        rel = rec.get("source_relative_path")
        if not isinstance(rel, str) or not rel:
            raise CatalogError(f"{required_label} record without source_relative_path: {rec!r}")
        if rec.get("source_set_sha256") != sid:
            raise CatalogError(
                f"mixed source-set id for {rel}: {rec.get('source_set_sha256')!r} != {sid!r}"
            )
        if not rec.get("ok"):
            raise CatalogError(
                f"{required_label} {rel} was not decoded successfully: {rec.get('error')!r}"
            )
        src_sha = rec.get("source_sha256")
        if not isinstance(src_sha, str) or not src_sha:
            raise CatalogError(f"{required_label} {rel} has no source_sha256")
        out_rel = rec.get("output")
        if not isinstance(out_rel, str) or not out_rel:
            raise CatalogError(f"{required_label} {rel} has no output filename recorded")
        out_path = root / out_rel
        if not out_path.is_file():
            raise CatalogError(f"{required_label} output missing (stale dataset): {out_path}")
        if sha256_file(out_path) != rec.get("output_sha256"):
            raise CatalogError(
                f"{required_label} output sha256 mismatch (tampered/stale): {out_path}"
            )
        if verify_source:
            src_path = rec.get("source_path")
            if not isinstance(src_path, str) or not src_path:
                raise CatalogError(f"{required_label} {rel} has no source_path")
            src = Path(src_path)
            if not src.is_file():
                raise CatalogError(f"{required_label} source missing (stale dataset): {src}")
            if sha256_file(src) != src_sha:
                raise CatalogError(f"{required_label} source sha256 mismatch (stale): {src}")
    return selected


def manifest_sha256(decoded_dir) -> str:
    """sha256 of the decoder provenance file itself."""
    return sha256_file(resolve(decoded_dir) / PROVENANCE_NAME)
