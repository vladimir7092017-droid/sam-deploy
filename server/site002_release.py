#!/usr/bin/env python3
"""Prepare, publish or roll back reviewed, byte-exact HTML contact edits."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

CONTACT = b"Angarlp@yandex.ru"
LEGACY = b"smartangar@yandex.ru"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspected_file(root, name):
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".html":
        raise ValueError("Each target must be a relative HTML path")
    path = root / relative
    info = path.lstat()
    if path.resolve() != path or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"Target is not a regular, unlinked HTML file: {path}")
    return path


def replace_contact(data, edits):
    for edit in edits:
        before = edit["before"].encode()
        after = edit["after"].encode()
        if CONTACT.lower() not in after.lower() or LEGACY.lower() in after.lower():
            raise ValueError("Replacement must retain only the approved contact")
        if LEGACY.lower() not in before.lower() or data.count(before) != 1:
            raise ValueError("Expected exactly one matching legacy contact fragment")
        if any(token in fragment.lower() for token in (b"<form", b"</form", b"<script", b"</script")
               for fragment in (before, after)):
            raise ValueError("Contact fragments cannot include scripts or forms")
        data = data.replace(before, after, 1)
    return data


def staged_file(path, data):
    if path.stat().st_uid != os.geteuid():
        raise PermissionError(f"Publisher does not own {path}")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".site002-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.chown(temporary, -1, path.stat().st_gid)
            shutil.copystat(path, temporary, follow_symlinks=False)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    return temporary


def update_files(changes):
    staged = []
    replaced = []
    try:
        for path, current, updated in changes:
            staged.append((path, current, updated, staged_file(path, updated)))
        for path, current, updated, temporary in staged:
            if path.read_bytes() != current:
                raise RuntimeError(f"File changed after preflight: {path}")
            os.replace(temporary, path)
            replaced.append((path, current, updated))
    except BaseException:
        for path, current, updated in reversed(replaced):
            if path.read_bytes() == updated:
                os.replace(staged_file(path, current), path)
        raise
    finally:
        for _, _, _, temporary in staged:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "publish", "rollback"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error("Run as the unprivileged publisher")
    manifest_bytes = args.manifest.read_bytes()
    sites = json.loads(manifest_bytes)["sites"]
    roots = [Path(site["root"]).resolve(strict=True) for site in sites]
    if len(roots) != 3 or len(set(roots)) != 3:
        parser.error("The manifest must identify three distinct roots")
    backup = args.backup.resolve()
    if any(backup.is_relative_to(root) or root.is_relative_to(backup) for root in roots):
        parser.error("The private backup must be separate from document roots")

    os.umask(0o077)
    if args.operation == "prepare":
        backup.mkdir(mode=0o700)
        (backup / "manifest.sha256").write_text(digest(manifest_bytes))
    else:
        info = backup.stat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            parser.error("The backup directory must be private and owned by the publisher")
        if (backup / "manifest.sha256").read_text() != digest(manifest_bytes):
            parser.error("Manifest changed after preparation")

    changes = []
    seen = set()
    for site, root in zip(sites, roots):
        for file in site["files"]:
            path = inspected_file(root, file["path"])
            if path in seen:
                parser.error("The manifest lists a file twice")
            seen.add(path)
            backup_file = backup / str(len(seen))
            current = path.read_bytes()
            original = current if args.operation == "prepare" else backup_file.read_bytes()
            if digest(original) != file["sha256"]:
                parser.error(f"Original does not match the reviewed hash: {path}")
            updated = replace_contact(original, file["edits"])
            if updated == original:
                parser.error("The reviewed edits do not change the file")
            if args.operation == "prepare":
                backup_file.write_bytes(original)
                print(f"Prepared {path.name} ({digest(updated)})")
            elif args.operation == "publish":
                changes.append((path, original, updated))
            elif current == updated:
                changes.append((path, updated, original))
            elif current != original:
                parser.error(f"Rollback refused because the file changed: {path}")
    if not seen:
        parser.error("The manifest has no file entries")
    if args.operation != "prepare":
        for path, expected, _ in changes:
            if path.read_bytes() != expected:
                parser.error(f"File changed since review: {path}")
        update_files(changes)


if __name__ == "__main__":
    main()
