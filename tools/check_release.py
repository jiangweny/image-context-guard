#!/usr/bin/env python3
"""Limited release hygiene and relative-document-link checks; not a secret scanner."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', '.ruff_cache'}
PRIVATE_DIRS = {'sessions', 'archived_sessions', 'image-context-backups',
                'image-context-guard-install-backups', 'outputs', 'local-config'}
PRIVATE_NAMES = {'auth.json', 'config.toml', 'runtime.json', '.env'}
REQUIRED = ['README.md', 'README.en.md', 'LICENSE', '.gitignore', '.gitattributes',
            'requirements.txt', 'icg.py', 'install.py', 'tests/test_guard.py',
            'docs/FIRST_GITHUB_UPLOAD.md', 'docs/VALIDATION.md', 'examples/demo.png',
            'skills/image-context-guard/SKILL.md', '.github/workflows/tests.yml']


def check(root):
    errors = []
    files = []
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.is_symlink():
            errors.append(str(relative) + ': unexpected symlink')
            continue
        if not path.is_file():
            continue
        files.append(path)
        if (path.name in PRIVATE_NAMES or path.name.startswith('.env.') or
                any(part in PRIVATE_DIRS for part in relative.parts) or
                path.suffix in ('.jsonl', '.bak', '.log') or '.sqlite' in path.name):
            errors.append(str(relative) + ': local/private artifact must not be published')
        if path.stat().st_size > 1024 * 1024:
            errors.append(str(relative) + ': unexpected file over 1 MiB')
        if path.suffix in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
            if relative.as_posix() not in {'examples/demo.png', '封面.jpg'}:
                errors.append(str(relative) + ': only the approved demo and cover images belong in this release')
            continue
        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeError:
            errors.append(str(relative) + ': unexpected binary file')
            continue
        if '\0' in content:
            errors.append(str(relative) + ': NUL byte in text')
        if re.search(r'\bsk-[A-Za-z0-9_-]{20,}\b', content):
            errors.append(str(relative) + ': possible credential')
        if re.search(r'data:image/[^;,]+;base64,[A-Za-z0-9+/]{120,}', content):
            errors.append(str(relative) + ': embedded image payload')
        if path.suffix == '.md':
            for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', content):
                target = target.split('#', 1)[0]
                if not target or '://' in target or target.startswith('mailto:'):
                    continue
                if not (path.parent / target).exists():
                    errors.append(str(relative) + ': broken local link ' + target)
    for required in REQUIRED:
        if not (root / required).is_file():
            errors.append('Missing required file: ' + required)
    return {'status': 'pass' if not errors else 'fail', 'files_checked': len(files),
            'bytes_checked': sum(p.stat().st_size for p in files), 'errors': errors,
            'note': 'Limited hygiene checks only; review the actual files before publishing.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    result = check(parser.parse_args().root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result['status'] == 'pass' else 1)
