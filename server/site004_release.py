#!/usr/bin/env python3
"""SITE-004: exact-hash, HTML-only public-contact release for смартангар.рф.

Not a general-purpose remote shell or general replacement utility. An authorized
server administrator must install it and a reviewed manifest before use.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

ROOT = Path('/var/www/smartangar-rf/public_html')
BACKUP = Path('/home/site-deploy/site004-backup')
MANIFEST = Path('/etc/site-deploy/site004-manifest.json')
BEFORE = b'Angarlp@yandex.ru'
AFTER = b'smartangar@yandex.ru'
MAX_HTML_BYTES = 12 * 1024 * 1024
PROTECTED = re.compile(rb'<(form|script)\b[^>]*>.*?</\1\s*>', re.I | re.S)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inspect_path(root, name, require_owner=False):
    relative = Path(name)
    if (relative.is_absolute() or not relative.parts or '..' in relative.parts
            or relative.suffix.lower() not in ('.html', '.htm')):
        raise ValueError('Only relative HTML paths are allowed')
    current = root
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError('Symlinks are forbidden in paths')
    s = current.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
        raise ValueError('Target must be a singly-linked regular file')
    if require_owner and s.st_uid != os.geteuid():
        raise PermissionError('site-deploy must own each reviewed HTML file')
    if s.st_size > MAX_HTML_BYTES:
        raise ValueError('HTML file too large for this release')
    return current


def protected_fragment(data, position):
    # A malformed/unclosed form or script is protected too; fail closed.
    state = {'form': 0, 'script': 0}
    for tag in re.finditer(rb'<(/?)(form|script)\b[^>]*>', data[:position], re.I | re.S):
        name = tag.group(2).decode('ascii').lower()
        state[name] = max(0, state[name] + (-1 if tag.group(1) else 1))
    if any(state.values()):
        return True
    prefix = data[:position].lower()
    for tag in (b'form', b'script'):
        open_pos = prefix.rfind(b'<' + tag)
        if open_pos > prefix.rfind(b'</' + tag) and prefix.find(b'>', open_pos) == -1:
            return True
    last_lt, last_gt = prefix.rfind(b'<'), prefix.rfind(b'>')
    if last_lt > last_gt:
        tag_text = prefix[last_lt:]
        # Only mailto anchor attributes can be edited inside an HTML tag.
        return not (tag_text.startswith(b'<a ') and b'mailto:' in tag_text)
    return False


def apply_exact_edits(original, edits):
    if not edits or not isinstance(edits, list):
        raise ValueError('A reviewed nonempty edit list is required')
    updated = original
    for edit in edits:
        before = edit['before'].encode('utf-8')
        if before.count(BEFORE) != 1 or len(before) > 2000:
            raise ValueError('An edit must contain exactly one approved old email')
        if updated.count(before) != 1:
            raise ValueError('The exact reviewed fragment is not unique')
        location = updated.index(before) + before.index(BEFORE)
        if protected_fragment(updated, location):
            raise ValueError('Cannot edit HTML form/script or unsafe tag attributes')
        updated = updated.replace(before, before.replace(BEFORE, AFTER, 1), 1)
    if [m.group(0) for m in PROTECTED.finditer(original)] != [m.group(0) for m in PROTECTED.finditer(updated)]:
        raise ValueError('Form or script content changed')
    return updated


def load_manifest(data, root):
    manifest = json.loads(data)
    if manifest.get('domain') != 'смартангар.рф' or manifest.get('root') != str(root):
        raise ValueError('Manifest does not identify the approved site')
    files = manifest.get('files')
    if not isinstance(files, list) or not files or len(files) > 100:
        raise ValueError('Manifest must have 1–100 reviewed HTML files')
    if len({item['path'] for item in files}) != len(files):
        raise ValueError('Duplicate file in manifest')
    return files


def file_plan(root, files, backup=None):
    plan = []
    for i, entry in enumerate(files):
        path = inspect_path(root, entry['path'], require_owner=True)
        current = path.read_bytes()
        if backup is None:
            original = current
        else:
            original = (backup / f'{i:03}.original').read_bytes()
        if sha(original) != entry['sha256']:
            raise ValueError('Original sha256 does not match reviewed manifest')
        updated = apply_exact_edits(original, entry['edits'])
        if current not in (original, updated):
            raise ValueError('Server HTML differs from reviewed original or target')
        plan.append((path, current, original, updated))
    return plan


def create_stage(path, data):
    original_stat = path.stat()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.site004-', delete=False) as out:
        tmp = Path(out.name)
        try:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
            os.chown(tmp, original_stat.st_uid, original_stat.st_gid)
            os.chmod(tmp, stat.S_IMODE(original_stat.st_mode))
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    return tmp


def atomic_updates(changes):
    staged, replaced = [], []
    try:
        for path, expected, desired in changes:
            staged.append((path, expected, desired, create_stage(path, desired)))
        for path, expected, desired, temp in staged:
            if path.read_bytes() != expected:
                raise ValueError('File changed since preflight')
            os.replace(temp, path)
            replaced.append((path, expected, desired))
    except BaseException:
        for path, old, new in reversed(replaced):
            if path.read_bytes() == new:
                os.replace(create_stage(path, old), path)
        raise
    finally:
        for _, _, _, temp in staged:
            temp.unlink(missing_ok=True)


def inventory(root):
    rows = []
    for path in sorted(root.rglob('*')):
        if path.suffix.lower() not in ('.html', '.htm') or path.is_symlink():
            continue
        try:
            target = inspect_path(root, str(path.relative_to(root)))
            content = target.read_bytes()
        except (ValueError, PermissionError, OSError):
            continue
        old_count, new_count = content.count(BEFORE), content.count(AFTER)
        if old_count or new_count:
            rows.append({'path': str(target.relative_to(root)), 'sha256': sha(content),
                         'current_email_count': old_count, 'desired_email_count': new_count})
    return rows


def execute(operation, root=ROOT, manifest_path=MANIFEST, backup=BACKUP):
    if os.geteuid() == 0:
        raise PermissionError('Do not run release as root')
    # Serialize all operations against the same backup namespace.
    lock_path = backup.parent / (backup.name + '.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        s = os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_uid != os.geteuid() or s.st_nlink != 1 or stat.S_IMODE(s.st_mode) & 0o077:
            raise PermissionError('Unsafe release lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _execute_locked(operation, root, manifest_path, backup)
    finally:
        os.close(fd)


def _execute_locked(operation, root, manifest_path, backup):
    if os.geteuid() == 0:
        raise PermissionError('Do not run release as root')
    root = root.resolve(strict=True)
    if operation == 'inventory':
        return {'domain': 'смартангар.рф', 'files': inventory(root)}
    raw = manifest_path.read_bytes()
    files = load_manifest(raw, root)
    backup = backup.resolve()
    if backup.is_relative_to(root) or root.is_relative_to(backup):
        raise ValueError('Backup must be outside the live document root')
    if operation == 'prepare':
        plan = file_plan(root, files)
        # Do not silently replace an existing backup / previously approved plan.
        backup.mkdir(mode=0o700)
        try:
            (backup / 'manifest.sha256').write_text(sha(raw), encoding='ascii')
            for i, (_, _, original, updated) in enumerate(plan):
                (backup / f'{i:03}.original').write_bytes(original)
                (backup / f'{i:03}.updated.sha256').write_text(sha(updated), encoding='ascii')
        except BaseException:
            shutil.rmtree(backup)
            raise
        return {'prepared': len(plan), 'backup': str(backup)}
    bs = backup.stat()
    if bs.st_uid != os.geteuid() or (stat.S_IMODE(bs.st_mode) & 0o077):
        raise PermissionError('Backup must be private and owned by site-deploy')
    if (backup / 'manifest.sha256').read_text(encoding='ascii') != sha(raw):
        raise ValueError('Reviewed manifest changed after prepare')
    plan = file_plan(root, files, backup=backup)
    for i, (_, _, _, updated) in enumerate(plan):
        if (backup / f'{i:03}.updated.sha256').read_text(encoding='ascii') != sha(updated):
            raise ValueError('Target content hash does not match prepare')
    changes = []
    for path, current, original, updated in plan:
        if operation == 'publish':
            if current != original:
                raise ValueError('Publish refuses a changed/already published file')
            changes.append((path, original, updated))
        elif operation == 'rollback':
            if current == updated:
                changes.append((path, updated, original))
            elif current != original:
                raise ValueError('Rollback refuses unexpected content')
        else:
            raise ValueError('Invalid operation')
    atomic_updates(changes)
    return {'operation': operation, 'updated': len(changes)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('inventory', 'prepare', 'publish', 'rollback'))
    args = parser.parse_args()
    print(json.dumps(execute(args.operation), ensure_ascii=False))
