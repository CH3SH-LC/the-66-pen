#!/usr/bin/env python3
"""Extract the editor's encrypted asset archives.

`Resource/BeyondAssets/assets.bin` and
`Resource/BeyondAssets/beyondeditorassets.bin` are single-entry
ZipCrypto archives whose single member carries the same name as the file. The
password is not a guess: it is the string literal `G16F153D` sitting next to the
path constant in the editor's own loader --

    RtdntcKoSeyQejJV6wqv.g5cstNKoCeJmiSQXEnJs.cs:859   "Resource/BeyondAssets/assets.bin"
    RtdntcKoSeyQejJV6wqv.g5cstNKoCeJmiSQXEnJs.cs:860   "G16F153D"
    RtdntcKoSeyQejJV6wqv.g5cstNKoCeJmiSQXEnJs.cs:861   File.OpenRead(...)
    RtdntcKoSeyQejJV6wqv.g5cstNKoCeJmiSQXEnJs.cs:872   new ZipInputStream(fileStream)

Both decrypted payloads are themselves ordinary ZIP archives.
Method 8 (deflate) + flag bit 0 (encrypted) => traditional PKWARE ZipCrypto, not AES.
That encryption flag is a production requirement, not a convenience: an outer
entry that reports itself unencrypted is rejected rather than decoded.

Read-only with respect to the game install: archives are opened for reading, output
goes only to the new directory given with --out.

Usage:
    python extract-assets-bin.py --out DIR [--dir SRCDIR] [--manifest FILE]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog_inputs import (  # noqa: E402
    SCHEMA_VERSION,
    CatalogError,
    ensure_absent,
    ensure_fresh_dir,
    ensure_no_overlap,
    exclusive_write_text,
    resolve,
    sha256_file,
    source_set_id,
)

DEFAULT_DIR = Path("D:/games/Genshin Impact Game/BeyondAssets/BeyondAssistEditor/Resource/BeyondAssets")
PASSWORD = b"G16F153D"
ARCHIVES = ["beyondeditorassets.bin", "assets.bin"]

STREAM_CHUNK = 1 << 20



def inspect_inner_archive(inner: zipfile.ZipFile) -> dict:
    """Read every member to EOF for CRC and content SHA256; never expand paths.

    In the 7.1 loader nJZThCjwwiOaLrrs2Blj.xTDtFIjwZh1Tq2bXo5t7.cs,
    lines 870/893/923 pass the same text2 (string offset 112016) to the
    ZipInputStream.Password setter for both layers. The 7.1 proxy map resolves
    cXCc41AOP9V2q3v2Lj9u.lOcAMW5QROL to that setter. This is not a key guess.
    """
    entries = inner.infolist()
    if not entries:
        raise CatalogError("inner ZIP has no entries")
    if len({e.filename for e in entries}) != len(entries):
        raise CatalogError("inner ZIP has duplicate member names")
    members = []
    for entry in entries:
        digest = hashlib.sha256()
        size = 0
        try:
            with inner.open(entry, pwd=PASSWORD) as fh:
                while block := fh.read(STREAM_CHUNK):
                    digest.update(block)
                    size += len(block)
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise CatalogError(f"inner entry {entry.filename!r} decryption/CRC failed: {exc}") from exc
        if size != entry.file_size:
            raise CatalogError(f"inner entry {entry.filename!r} size mismatch")
        members.append({"name": entry.filename, "size": size, "crc": entry.CRC,
                        "encrypted": bool(entry.flag_bits & 1), "sha256": digest.hexdigest()})
    return {"entries": len(entries), "crc_checked": len(entries),
            "crc_checked_unencrypted": sum(not (e.flag_bits & 1) for e in entries),
            "members": members}


def inspect_archive(path: Path, staging: Path, require_encryption: bool = True) -> dict:
    """Validate + decrypt one outer archive, staging its payload as <stem>.dec.

    Nothing is written outside ``staging``. Any structural surprise (missing
    file, empty file, wrong entry count, directory entry, unexpected member
    name, empty payload, non-ZIP payload, empty inner archive, inner CRC
    failure) raises CatalogError. ``require_encryption`` is a production
    criterion and stays True for real runs; the test suite lowers it only to
    exercise the surrounding structure with a stdlib-written fixture, because
    the stdlib cannot write ZipCrypto archives.
    """
    if not path.is_file():
        raise CatalogError(f"archive missing or not a file: {path}")
    expected_member = path.name
    source_sha = sha256_file(path)

    try:
        outer = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise CatalogError(f"{path.name}: not a readable ZIP archive: {exc}") from exc

    with outer:
        infos = outer.infolist()
        if len(infos) != 1:
            raise CatalogError(
                f"{path.name}: expected exactly one outer entry, found {len(infos)}"
            )
        info = infos[0]
        if info.is_dir():
            raise CatalogError(f"{path.name}: outer entry is a directory: {info.filename!r}")
        # The output path is built from the expected on-disk file name, never
        # from the archive-supplied member name.
        if info.filename != expected_member:
            raise CatalogError(
                f"{path.name}: unexpected outer member name {info.filename!r}; "
                "refusing names supplied by the archive"
            )
        encrypted = bool(info.flag_bits & 1)
        if require_encryption and not encrypted:
            raise CatalogError(
                f"{path.name}: outer entry is not encrypted; "
                "production archives are ZipCrypto-encrypted"
            )

        out_name = path.stem + ".dec"
        tmp = staging / (out_name + ".tmp")
        digest = hashlib.sha256()
        written = 0
        outer.setpassword(PASSWORD)
        try:
            with outer.open(info, "r") as src, open(tmp, "xb") as dst:
                while True:
                    block = src.read(STREAM_CHUNK)
                    if not block:
                        break
                    digest.update(block)
                    dst.write(block)
                    written += len(block)
        except (zipfile.BadZipFile, RuntimeError) as exc:
            # RuntimeError => wrong password; BadZipFile => CRC mismatch at EOF.
            raise CatalogError(f"{path.name}: decryption/CRC failed: {exc}") from exc
        if written == 0:
            raise CatalogError(f"{path.name}: decrypted payload is empty")

        try:
            inner = zipfile.ZipFile(tmp)
        except (zipfile.BadZipFile, OSError) as exc:
            raise CatalogError(
                f"{path.name}: decrypted payload is not a ZIP archive: {exc}"
            ) from exc
        with inner:
            inner_report = inspect_inner_archive(inner)

    if sha256_file(path) != source_sha:
        raise CatalogError(f"{path.name}: archive changed while reading")
    return {
        "_tmp": tmp.name,
        "output": out_name,
        "source_path": str(path),
        "size": path.stat().st_size,
        "sha256": source_sha,
        "decrypted_sha256": digest.hexdigest(),
        "decrypted_size": written,
        "outer_entries": len(infos),
        "outer_member": info.filename,
        "encrypted": encrypted,
        "compress_type": info.compress_type,
        "inner": inner_report,
    }


def extract_archives(
    src,
    out,
    manifest=None,
    archives=None,
    require_encryption: bool = True,
) -> dict:
    """Validate every input archive, then publish all outputs, then the manifest.

    Inputs are fully inspected into a staging directory inside --out first. The
    staging directory is always removed; the manifest is written last, so a
    partial run never leaves a manifest claiming success.
    """
    src = resolve(src)
    out = resolve(out)
    manifest = resolve(manifest) if manifest else out / "assets-manifest.json"
    names = list(archives or ARCHIVES)

    if not src.is_dir():
        raise CatalogError(f"source install directory missing: {src}")
    ensure_no_overlap(src, out, "source install", "output")
    ensure_no_overlap(src, manifest, "source install", "manifest")
    ensure_absent(manifest, "manifest")

    if not names or len(set(names)) != len(names) or any(Path(n).name != n for n in names):
        raise CatalogError("invalid archive names")
    for name in names:
        if not (src / name).is_file():
            raise CatalogError(f"archive missing: {src / name}")
        dest = out / (Path(name).stem + ".dec")
        if manifest == dest or dest in manifest.parents:
            raise CatalogError("manifest conflicts with decrypted output")
    created_out = not out.exists()
    out = ensure_fresh_dir(out, "output directory")

    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=out))
    try:
        records = []
        for name in names:
            records.append(inspect_archive(src / name, staging, require_encryption))

        # Every input validated. Only now are the outputs published.
        for rec in records:
            with (staging / rec.pop("_tmp")).open("rb") as source, (out / rec["output"]).open("xb") as target:
                shutil.copyfileobj(source, target, STREAM_CHUNK)

        set_id = source_set_id([(Path(r["source_path"]).name, r["sha256"]) for r in records])
        manifest_obj = {
            "tool": "extract-assets-bin.py",
            "schema_version": SCHEMA_VERSION,
            "source_root": str(src),
            "source_set_id": set_id,
            "cipher": "zipcrypto" if all(r["encrypted"] for r in records) else "none-detected",
            "encryption_required": bool(require_encryption),
            "password_sha256": hashlib.sha256(PASSWORD).hexdigest(),
            "archives": records,
        }
        exclusive_write_text(
            manifest, json.dumps(manifest_obj, ensure_ascii=False, indent=1), "manifest"
        )
        return manifest_obj
    except Exception:
        if created_out:
            try:
                if not any(out.iterdir()):
                    out.rmdir()
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=str(DEFAULT_DIR), help="read-only install directory")
    ap.add_argument("--out", required=True, help="new/empty output directory (required)")
    ap.add_argument("--manifest", default=None, help="manifest path (default: <out>/assets-manifest.json)")
    args = ap.parse_args()

    try:
        manifest_obj = extract_archives(args.dir, args.out, args.manifest)
    except (CatalogError, OSError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for rec in manifest_obj["archives"]:
        print(
            f"{Path(rec['source_path']).name}: size={rec['size']} encrypted={rec['encrypted']} "
            f"decrypted={rec['decrypted_size']} sha256={rec['decrypted_sha256']} "
            f"inner-entries={rec['inner']['entries']} "
            f"crc-checked={rec['inner']['crc_checked']} -> {rec['output']}"
        )
    print(f"source_set_id={manifest_obj['source_set_id']}")
    print(f"wrote manifest -> {resolve(args.manifest) if args.manifest else resolve(args.out) / 'assets-manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
