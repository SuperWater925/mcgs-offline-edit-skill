"""Read-only repository checks; --update-manifest explicitly refreshes file hashes.

No database, vendor software, credentials or device access is required.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

MANIFEST = 'references/package-files.sha256.json'
EXCLUDED_DIRS = {'.git', '__pycache__', '.venv', 'local-artifacts'}
EXCLUDED_SUFFIXES = {'.pyc', '.pyo'}


def package_files(root: Path) -> list[Path]:
    files = []
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS)
        for name in names:
            path = Path(current) / name
            rel = path.relative_to(root).as_posix()
            if rel == '.git' or path.suffix.lower() in EXCLUDED_SUFFIXES:
                continue
            if path.is_symlink():
                raise ValueError(f'Symlink is not a packaged file: {rel}')
            if rel != MANIFEST:
                files.append(path)
    return sorted(files, key=lambda p: p.relative_to(root).as_posix().casefold())


def file_manifest(root: Path, paths: list[Path]) -> dict:
    rows = []
    seen = set()
    for path in paths:
        rel = path.relative_to(root).as_posix()
        if rel.casefold() in seen:
            raise ValueError(f'Case-insensitive duplicate path: {rel}')
        seen.add(rel.casefold())
        raw = path.read_bytes()
        rows.append({'file': rel, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    descriptor = ''.join(f"{r['file']}\0{r['sha256']}\n" for r in rows).encode('utf-8')
    return {'schema': 1, 'self_excluded': True, 'file_count': len(rows),
            'descriptor_sha256': hashlib.sha256(descriptor).hexdigest(), 'files': rows}


def markdown_without_code(text: str) -> str:
    lines = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(re.sub(r'`[^`]*`', '', line))
    return '\n'.join(lines)


def check_sources(root: Path, paths: list[Path]) -> tuple[list[str], dict]:
    errors = []
    counts = {'python': 0, 'json': 0, 'markdown_link_targets': 0, 'skills': 0}
    for path in paths:
        rel = path.relative_to(root).as_posix()
        try:
            if path.suffix == '.py':
                compile(path.read_bytes(), rel, 'exec', flags=ast.PyCF_ONLY_AST)
                counts['python'] += 1
            elif path.suffix == '.json':
                json.loads(path.read_text(encoding='utf-8-sig'))
                counts['json'] += 1
            elif path.suffix.lower() == '.md':
                text = path.read_text(encoding='utf-8-sig')
                if path.name == 'SKILL.md':
                    match = re.match(r'\A---\s*\n(.*?)\n---(?:\s*\n|$)', text, re.S)
                    if not match:
                        raise ValueError('Missing SKILL.md frontmatter')
                    head = match.group(1)
                    name = re.search(r'^name:\s*([a-z0-9-]{1,64})\s*$', head, re.M)
                    description = re.search(r'^description:\s*\S.+$', head, re.M)
                    if not name or not description:
                        raise ValueError('Missing or invalid skill name/description')
                    counts['skills'] += 1
                for target in re.findall(r'\]\(([^)\n]+)\)', markdown_without_code(text)):
                    target = target.strip()
                    if target.startswith('<') and '>' in target:
                        target = target[1:target.index('>')]
                    else:
                        target = re.split(r'\s+[\"\']', target, maxsplit=1)[0]
                    link = urlsplit(target)
                    if link.scheme or link.netloc or not link.path:
                        continue
                    destination = (path.parent / unquote(link.path)).resolve()
                    if not destination.is_relative_to(root) or not destination.exists():
                        errors.append(f'{rel}: missing/escaping local link {target}')
                    counts['markdown_link_targets'] += 1
        except (ValueError, SyntaxError, UnicodeError, OSError) as exc:
            errors.append(f'{rel}: {exc}')
    return errors, counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--update-manifest', action='store_true', help='Refresh only the file hash manifest')
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / 'SKILL.md').is_file():
        parser.error('Repository root must contain SKILL.md')
    paths = package_files(root)
    expected = file_manifest(root, paths)
    errors, counts = check_sources(root, paths)
    manifest_path = root / MANIFEST
    if args.update_manifest:
        if errors:
            errors.append('Manifest not updated because source checks failed')
        else:
            manifest_path.write_bytes((json.dumps(expected, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    else:
        try:
            actual = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
            if actual != expected:
                errors.append('File manifest differs; review changes and run --update-manifest')
        except (OSError, ValueError) as exc:
            errors.append(f'{MANIFEST}: {exc}')
    print(json.dumps({'passed': not errors, 'files': len(paths), 'checked': counts,
                      'manifest_updated': args.update_manifest and not errors,
                      'errors': errors, 'vendor_compile_verified': False}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
