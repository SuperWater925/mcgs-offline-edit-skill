"""Build a verified portable skill ZIP, excluding local test artifacts."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from check_repository import MANIFEST, file_manifest, package_files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True, help='Skill release tag, e.g. v2026.10.30')
    parser.add_argument('--out', type=Path, required=True, help='New directory outside sources or in local-artifacts/')
    args = parser.parse_args()
    if not re.fullmatch(r'v[0-9]+(?:\.[0-9]+){2}(?:-[a-z0-9.-]+)?', args.version):
        parser.error('Use a valid skill release tag')
    root = Path(__file__).resolve().parents[1]
    output = args.out.resolve()
    if output.exists():
        parser.error('Output must be a new directory')
    if output.is_relative_to(root) and not output.is_relative_to(root / 'local-artifacts'):
        parser.error('In-repository output must stay in local-artifacts/')
    checked = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(root / 'scripts/check_repository.py')],
                             capture_output=True, text=True, encoding='utf-8')
    if checked.returncode:
        print(checked.stdout, end='')
        print(checked.stderr, file=sys.stderr, end='')
        return checked.returncode
    files = package_files(root)
    forbidden = {'.mcs', '.mcp', '.mdb', '.accdb', '.exe', '.dll', '.so', '.chm', '.zip', '.rar', '.7z', '.key', '.pem', '.pfx'}
    for path in files:
        if (path.suffix.lower() in forbidden or path.name.startswith('.env')
                or path.read_bytes()[:4] in (b'\x7fELF', b'MZ\x90\x00')):
            parser.error(f'Unexpected release payload: {path.relative_to(root)}')
    expected = json.loads((root / MANIFEST).read_text(encoding='utf-8-sig'))
    if file_manifest(root, files) != expected:
        parser.error('Source files changed during validation')
    output.mkdir(parents=True)
    archive_path = output / f'mcgs-offline-edit-{args.version}.zip'
    included = sorted(files + [root / MANIFEST], key=lambda p: p.relative_to(root).as_posix().casefold())
    with zipfile.ZipFile(archive_path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in included:
            info = zipfile.ZipInfo('mcgs-offline-edit/' + path.relative_to(root).as_posix(), (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP CRC verification failed')
        entries = {p['file']: p['sha256'] for p in expected['files']}
        entries[MANIFEST] = hashlib.sha256((root / MANIFEST).read_bytes()).hexdigest()
        assert set(archive.namelist()) == {'mcgs-offline-edit/' + p for p in entries}
        for name, digest in entries.items():
            if hashlib.sha256(archive.read('mcgs-offline-edit/' + name)).hexdigest() != digest:
                raise ValueError(f'Archived file differs: {name}')
    if file_manifest(root, package_files(root)) != expected:
        raise ValueError('Source files changed while packaging')
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text(f'{digest}  {archive_path.name}\n', encoding='ascii')
    print(json.dumps({'passed': True, 'archive': str(archive_path), 'sha256': digest,
                      'files': len(included), 'root': 'mcgs-offline-edit'}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
