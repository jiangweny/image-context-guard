#!/usr/bin/env python3
"""Install the bundled Codex skill; optionally merge a managed global rule."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'skills' / 'image-context-guard'
FILES = ['SKILL.md', 'agents/openai.yaml', 'references/recovery.md', 'references/native-agents.md',
         'scripts/read_image.py', 'scripts/prune_history.py']
START = '<!-- image-context-guard:start -->'
END = '<!-- image-context-guard:end -->'


def merge_rule(original, block):
    if original.count(START) != original.count(END) or original.count(START) > 1:
        raise ValueError('Malformed managed markers; no global rules changed.')
    if START in original:
        start, end = original.index(START), original.index(END)
        if end < start:
            raise ValueError('Reversed managed markers; no global rules changed.')
        return original[:start] + block + original[end + len(END):]
    return original + ('\n\n' if original and not original.endswith('\n\n') else '') + block + '\n'


def rule_block(destination):
    return '\n'.join([
        START, '## Image Context Guard', '',
        'For local image analysis, OCR or visual inspection, read the skill at:',
        str(destination / 'SKILL.md'), '',
        'Follow the backend preference in the installed runtime.json and the skill routing rules.',
        'Use an isolated native vision agent when available and permitted, or its independent API helper.',
        'Keep image payloads out of the parent conversation; return text and artifact paths only.',
        'Do not repeat a known-broken API route for each image. Bound agent concurrency and checkpoint work.',
        'Preserve image paths and written observations; never print image Base64 or API keys.',
        'Respect an explicit request for direct vision. This skill cannot remove images already',
        'loaded into a live conversation. Only clean an explicitly authorized, stopped history',
        'after saving a text checkpoint. Do not bypass writer locks or edit unrelated sessions.',
        END,
    ])


def atomic_write(path, data):
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def install(args):
    home = Path(args.codex_home).expanduser().resolve()
    parent = Path(args.skills_dir).expanduser().resolve() if args.skills_dir else home / 'skills'
    destination = parent / 'image-context-guard'
    rules = home / 'AGENTS.md'
    if destination.is_symlink() or (args.with_global_rule and rules.is_symlink()):
        raise ValueError('Refusing a symlink installation target.')
    if destination.resolve() == SOURCE.resolve():
        raise ValueError('Installation target must be separate from the source checkout.')
    if destination.exists() and (not destination.is_dir() or not args.replace):
        raise ValueError('Skill already exists; review it and pass --replace to back it up and replace it.')
    previous_runtime = {}
    if (destination / 'runtime.json').is_file():
        previous_runtime = json.loads((destination / 'runtime.json').read_text(encoding='utf-8'))
        if not isinstance(previous_runtime, dict):
            raise ValueError('Existing runtime.json must be an object; review it before replacement.')
    def preference(name, default):
        value = getattr(args, name, None)
        return value if value is not None else previous_runtime.get(name, default)
    runtime = {
        'python': sys.executable, 'installed_from': str(ROOT),
        'backend': preference('backend', 'auto'),
        'max_native_agents': preference('max_native_agents', 2),
        'no_progress_seconds': preference('no_progress_seconds', 300),
    }
    if runtime['backend'] not in ('auto', 'native-agent', 'api'):
        raise ValueError('Backend must be auto, native-agent or api.')
    if not isinstance(runtime['max_native_agents'], int) or not 1 <= runtime['max_native_agents'] <= 8:
        raise ValueError('max_native_agents must be between 1 and 8; actual client slots may be lower.')
    if not isinstance(runtime['no_progress_seconds'], int) or runtime['no_progress_seconds'] < 60:
        raise ValueError('no_progress_seconds must be at least 60; it triggers inspection, not automatic cancellation.')
    for name in FILES:
        if not (SOURCE / name).is_file() or (SOURCE / name).is_symlink():
            raise ValueError('Missing or unexpected source file: ' + name)
    original = updated = None
    if args.with_global_rule:
        if (home / 'AGENTS.override.md').exists():
            raise ValueError('AGENTS.override.md exists. Review instruction precedence before adding global rules.')
        original = rules.read_bytes() if rules.exists() else None
        updated = merge_rule(original.decode('utf-8') if original is not None else '', rule_block(destination)).encode('utf-8')
    result = {'status': 'preview' if args.dry_run else 'installed', 'skill': str(destination),
              'python': sys.executable, 'global_rule': str(rules) if args.with_global_rule else None,
              'backend': runtime['backend'], 'max_native_agents': runtime['max_native_agents'],
              'no_progress_seconds': runtime['no_progress_seconds']}
    if args.dry_run:
        return result
    parent.mkdir(parents=True, exist_ok=True)
    if args.with_global_rule:
        home.mkdir(parents=True, exist_ok=True)
    backup = None
    if destination.exists() or (original is not None and original != updated):
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = home / 'image-context-guard-install-backups' / stamp
        backup.mkdir(parents=True, mode=0o700)
        if destination.exists():
            shutil.copytree(destination, backup / 'skill', symlinks=True)
        if original is not None:
            atomic_write(backup / 'AGENTS.md.bak', original)
    staged = Path(tempfile.mkdtemp(prefix='.image-context-guard-', dir=parent))
    previous = parent / (staged.name + '-previous')
    try:
        for name in FILES:
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, target)
        atomic_write(staged / 'runtime.json', (json.dumps(runtime, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        if destination.exists():
            destination.rename(previous)
        try:
            staged.rename(destination)
        except Exception:
            if previous.exists():
                previous.rename(destination)
            raise
        if previous.exists():
            shutil.rmtree(previous)
        if args.with_global_rule and original != updated:
            current = rules.read_bytes() if rules.exists() else None
            if current != original:
                raise RuntimeError('Skill installed, but AGENTS.md changed concurrently; rule merge canceled.')
            atomic_write(rules, updated)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    result['backup'] = str(backup) if backup else None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home', default=os.environ.get('CODEX_HOME') or '~/.codex')
    parser.add_argument('--skills-dir', help='Override the skill discovery directory for your Codex client.')
    parser.add_argument('--with-global-rule', action='store_true', help='Merge the managed block into CODEX_HOME/AGENTS.md.')
    parser.add_argument('--backend', choices=['auto', 'native-agent', 'api'],
                        help='Skill routing preference. Defaults to auto; replacement preserves the previous preference.')
    parser.add_argument('--max-native-agents', type=int, choices=range(1, 9),
                        help='Concurrent native vision agents, default 2. Client slot limits still apply.')
    parser.add_argument('--no-progress-seconds', type=int,
                        help='Inspect a task after this interval without observable progress, default 300; not an auto-kill timer.')
    parser.add_argument('--replace', action='store_true', help='Back up and replace an existing skill.')
    parser.add_argument('--dry-run', action='store_true', help='Print destinations without writing files.')
    try:
        print(json.dumps(install(parser.parse_args()), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'status': 'error', 'error': str(error)[:700]}, ensure_ascii=False))
        sys.exit(1)


if __name__ == '__main__':
    main()
