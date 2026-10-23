#!/usr/bin/env python3
"""Audit embedded images, or prune/restore an explicitly selected unlocked history."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
try:
    import fcntl
except ImportError:
    fcntl = None
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import tempfile
import uuid

MARKER = {'type': 'input_text', 'text': '[Embedded historical image removed. Existing text is preserved; consult the saved checkpoint and original image source.]'}
IMAGE_URI = re.compile(r'^data:image/[^;,]+;base64,[A-Za-z0-9+/\r\n]+=*$')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def current_id():
    return os.environ.get('CODEX_THREAD_ID') or os.environ.get('CODEX_SESSION_ID')


def session_path(home, selector):
    # Compare canonical roots with canonical targets, including OS path aliases.
    home = Path(home).expanduser().resolve()
    if selector == 'current':
        selector = current_id()
        if not selector:
            raise ValueError('Current session ID is unavailable; provide an explicit UUID or path.')
    if '/' in selector or selector.endswith('.jsonl'):
        path = Path(selector).expanduser()
    else:
        uuid.UUID(selector)
        matches = []
        database = home / 'state_5.sqlite'
        if database.exists():
            try:
                with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as conn:
                    conn.execute('PRAGMA query_only=ON')
                    row = conn.execute('SELECT rollout_path FROM threads WHERE id=?', (selector,)).fetchone()
                    if row and Path(row[0]).exists():
                        matches = [Path(row[0])]
            except sqlite3.Error:
                pass  # Fall back to exact UUID filenames when the internal index changes.
        if not matches:
            for folder in ('sessions', 'archived_sessions'):
                matches.extend((home / folder).rglob('*' + selector + '.jsonl'))
        if len(matches) != 1:
            raise ValueError('Expected exactly one matching session file; provide its explicit path.')
        path = matches[0]
    if path.is_symlink():
        raise ValueError('Symlink session targets are not supported.')
    path = path.resolve(strict=True)
    if not path.is_file() or path.suffix != '.jsonl' or not any(path.is_relative_to(home / name) for name in ('sessions', 'archived_sessions')):
        raise ValueError('Target must be a JSONL under this Codex home sessions or archived_sessions.')
    return path


def read_records(path):
    with path.open('rb') as stream:
        raw = stream.read(os.fstat(stream.fileno()).st_size)
    if not raw.endswith(b'\n'):
        raise ValueError('Incomplete final JSONL record; no mutation performed.')
    items = [json.loads(line) for line in raw.splitlines()]
    if not items or items[0].get('type') != 'session_meta':
        raise ValueError('Session metadata is missing at the beginning of the file.')
    session_id = items[0]['payload']['id']
    uuid.UUID(session_id)
    return raw, items, session_id


def image_stats(value):
    if isinstance(value, str):
        return (1, len(value)) if IMAGE_URI.fullmatch(value) else (0, 0)
    values = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    count = size = 0
    for item in values:
        a, b = image_stats(item)
        count += a
        size += b
    return count, size


def sanitized(value):
    if isinstance(value, dict):
        url = value.get('image_url')
        if value.get('type') == 'input_image' and isinstance(url, str) and IMAGE_URI.fullmatch(url):
            if not set(value).issubset({'type', 'image_url', 'detail'}):
                raise ValueError('Unknown input_image metadata; extend support before modifying.')
            return dict(MARKER)
        return {k: sanitized(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitized(v) for v in value]
    return value


def audit(path):
    raw, items, sid = read_records(path)
    all_count = all_bytes = active_count = active_bytes = 0
    active_known = False
    usage = None
    for item in items:
        n, size = image_stats(item)
        all_count += n
        all_bytes += size
        payload = item.get('payload', {})
        if item.get('type') == 'compacted':
            history = payload.get('replacement_history')
            if isinstance(history, list):
                active_count = image_stats(history)[0]
                active_bytes = len(json.dumps(history, ensure_ascii=False).encode())
                active_known = True
        elif item.get('type') == 'response_item':
            active_count += image_stats(payload)[0]
            active_bytes += len(json.dumps(payload, ensure_ascii=False).encode())
        if payload.get('type') == 'token_count':
            usage = (payload.get('info') or {}).get('last_token_usage')
    return {'session_id': sid, 'path': str(path), 'records': len(items), 'disk_bytes': len(raw),
            'embedded_image_entries': all_count, 'encoded_image_chars': all_bytes,
            'estimated_history_image_entries': active_count, 'estimated_history_json_bytes': active_bytes,
            'reconstructed_after_compaction': active_known, 'last_recorded_usage': usage,
            'note': 'Disk and reconstructed-history sizes are not measured API request sizes. Usage records are historical.'}


@contextmanager
def writer_lock(home, sid):
    if fcntl is None:
        raise ValueError('History modification requires POSIX file locks. Only audit is supported on this platform.')
    if sid == current_id():
        raise ValueError('Refusing to modify the current conversation. Use isolated image reads or clean from another conversation after stopping it.')
    folder = home / 'thread-writer-locks'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (sid + '.lock')
    if path.is_symlink():
        raise ValueError('Unexpected symlink writer lock.')
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Codex still holds this session writer lock. Close/reload the owning window, then retry; no file changed.') from None
        yield
    finally:
        os.close(fd)


def replace_checked(path, data, expected_sha):
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.prune-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), stat.S_IMODE(path.stat().st_mode))
        if sha(path.read_bytes()) != expected_sha:
            raise ValueError('Session changed during preparation; replacement canceled.')
        os.replace(tmp, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        if sha(path.read_bytes()) != sha(data):
            raise RuntimeError('Post-write checksum mismatch; use the saved backup for recovery.')
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def prune(home, path, checkpoint, apply):
    info = audit(path)
    checkpoint = Path(checkpoint).expanduser().resolve(strict=True)
    if checkpoint == path or not checkpoint.is_file() or checkpoint.stat().st_size == 0:
        raise ValueError('Provide a separate, nonempty text handoff/checkpoint file.')
    if not apply or not info['embedded_image_entries']:
        return {'status': 'preview' if not apply else 'unchanged', **info, 'checkpoint': str(checkpoint)}
    with writer_lock(home, info['session_id']):
        raw, items, sid = read_records(path)
        if sid != info['session_id']:
            raise ValueError('Session identity changed; no mutation performed.')
        output = []
        removed = 0
        for line, item in zip(raw.splitlines(keepends=True), items):
            count = image_stats(item)[0]
            if not count:
                output.append(line)
                continue
            cleaned = sanitized(item)
            if image_stats(cleaned)[0]:
                raise ValueError('Embedded images in an unsupported shape remain; no file changed.')
            removed += count
            output.append(json.dumps(cleaned, ensure_ascii=False, separators=(',', ':')).encode() + b'\n')
        cleaned_raw = b''.join(output)
        rebuilt = [json.loads(line) for line in cleaned_raw.splitlines()]
        if len(rebuilt) != len(items) or any(sanitized(a) != b for a, b in zip(items, rebuilt)):
            raise RuntimeError('Non-image content changed; refusing replacement.')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup_dir = home / 'image-context-backups' / (stamp + '-' + sid)
        backup_dir.mkdir(parents=True, mode=0o700)
        backup = backup_dir / (path.name + '.bak')
        backup.write_bytes(raw)
        backup.chmod(0o600)
        if sha(backup.read_bytes()) != sha(raw):
            raise RuntimeError('Backup checksum mismatch.')
        manifest = {'session_id': sid, 'path': str(path), 'backup': str(backup),
                    'original_sha256': sha(raw), 'cleaned_sha256': sha(cleaned_raw),
                    'before_bytes': len(raw), 'after_bytes': len(cleaned_raw), 'removed_image_entries': removed,
                    'checkpoint': str(checkpoint), 'checkpoint_sha256': sha(checkpoint.read_bytes())}
        manifest_path = backup_dir / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        manifest_path.chmod(0o600)
        replace_checked(path, cleaned_raw, manifest['original_sha256'])
        return {'status': 'cleaned', **manifest, 'manifest': str(manifest_path), 'remaining_embedded_images': 0,
                'reload_required': True}


def restore(home, manifest_path, apply):
    home = Path(home).expanduser().resolve()
    manifest_path = Path(manifest_path).expanduser().resolve(strict=True)
    if not manifest_path.is_relative_to(home / 'image-context-backups'):
        raise ValueError('Use a manifest inside this Codex home image-context-backups directory.')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    path = session_path(home, manifest['path'])
    backup = Path(manifest['backup']).resolve(strict=True)
    if not backup.is_relative_to(manifest_path.parent):
        raise ValueError('Backup lies outside its manifest directory.')
    if not apply:
        return {'status': 'preview', 'path': str(path), 'backup': str(backup), 'action': 'restore'}
    with writer_lock(home, manifest['session_id']):
        raw = backup.read_bytes()
        if sha(raw) != manifest['original_sha256']:
            raise ValueError('Backup checksum mismatch.')
        if read_records(path)[2] != manifest['session_id'] or read_records(backup)[2] != manifest['session_id']:
            raise ValueError('Session identity does not match the manifest.')
        replace_checked(path, raw, manifest['cleaned_sha256'])
        return {'status': 'restored', 'path': str(path), 'bytes': len(raw)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home', default=os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    sub = parser.add_subparsers(dest='action', required=True)
    for command in ('audit', 'prune'):
        p = sub.add_parser(command)
        p.add_argument('--session', required=True)
        if command == 'prune':
            p.add_argument('--checkpoint', required=True)
            p.add_argument('--apply', action='store_true')
    p = sub.add_parser('restore')
    p.add_argument('--manifest', required=True)
    p.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    home = Path(args.codex_home).expanduser().resolve()
    if args.action == 'restore':
        result = restore(home, args.manifest, args.apply)
    else:
        path = session_path(home, args.session)
        result = audit(path) if args.action == 'audit' else prune(home, path, args.checkpoint, args.apply)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'error', 'error': str(error)[:700]}, ensure_ascii=False))
        sys.exit(1)
