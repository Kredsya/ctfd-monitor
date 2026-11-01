"""Bounded extraction into a fresh staging directory; never follows archive links."""
from pathlib import Path
import shutil
import stat
import tarfile
import zipfile


def extract(archive: Path, target: Path, max_bytes: int | None = None, cancelled=lambda: False) -> None:
    root = target.resolve()
    used = 0
    count = 0

    def copy(name, stream, size):
        nonlocal used, count
        count += 1
        destination = (root / name).resolve()
        if not destination.is_relative_to(root) or destination == root:
            raise ValueError('archive path escapes extraction directory')
        if count > 10000 or size < 0 or (max_bytes is not None and used + size > max_bytes):
            raise ValueError('archive exceeds extraction limits')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as output:
            while chunk := stream.read(128 * 1024):
                if cancelled():
                    raise RuntimeError('extraction cancelled')
                used += len(chunk)
                if max_bytes is not None and used > max_bytes:
                    raise ValueError('archive exceeds extraction limits')
                output.write(chunk)

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                if member.is_dir():
                    continue
                mode = member.external_attr >> 16
                if stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                    raise ValueError('archive links and special files are unsupported')
                with package.open(member) as stream:
                    copy(member.filename, stream, member.file_size)
    else:
        with tarfile.open(archive) as package:
            for member in package:
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError('archive links and special files are unsupported')
                with package.extractfile(member) as stream:
                    copy(member.name, stream, member.size)
