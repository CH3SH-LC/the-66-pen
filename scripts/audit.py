"""Offline distribution syntax, file links, credential patterns and binary audit."""
import ast
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE = {".runtime", ".git", "__pycache__", ".pytest_cache", "bin", "obj", "node_modules"}


def audit():
    errors, files, python_count = [], [], 0
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if not p.is_file() or set(rel.parts) & EXCLUDE:
            continue
        files.append(rel.as_posix())
        if p.suffix.lower() in {".dll", ".exe", ".gil", ".gip", ".gia", ".gir", ".pdb", ".png", ".jpg", ".mp4", ".db"}:
            errors.append({"file": rel.as_posix(), "error": "UNEXPECTED_BINARY"})
        if p.suffix in {".py", ".json", ".md", ".cs", ".cpp", ".h", ".inc", ".ps1", ".ts"}:
            text = p.read_text(encoding="utf-8-sig")
            # Examples/fixture tokens are short or obvious placeholders; real long patterns are refused.
            for pattern in [r"ghp_[A-Za-z0-9]{25,}", r"github_pat_[A-Za-z0-9_]{30,}",
                            r"sk-[A-Za-z0-9]{25,}", r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"]:
                if re.search(pattern, text):
                    errors.append({"file": rel.as_posix(), "error": "CREDENTIAL_PATTERN"})
            if p.suffix == ".py":
                python_count += 1
                try:
                    ast.parse(text)
                except SyntaxError as exc:
                    errors.append({"file": rel.as_posix(), "error": str(exc)})
            if p.suffix == ".json" and not p.name.startswith("tsconfig"):
                try:
                    json.loads(text)
                except ValueError as exc:
                    errors.append({"file": rel.as_posix(), "error": str(exc)})
            # Current hand-written entry docs have actual relative links.
            if p.suffix == ".md" and (rel.parts[0] != "docs" or len(rel.parts) <= 2):
                for url in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", text):
                    if "://" in url or url.startswith("#"):
                        continue
                    path = url.split("#")[0]
                    if not (p.parent / path).exists():
                        errors.append({"file": rel.as_posix(), "error": "BROKEN_LINK:" + url})
    return {"ok": not errors, "files": len(files), "pythonFiles": python_count, "errors": errors}


if __name__ == "__main__":
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
