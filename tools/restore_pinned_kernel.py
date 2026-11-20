#!/usr/bin/env python3
"""Restore the preserved public K70 kernel, checking the original artifact bytes."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import stat
import zipfile

PLATFORM_SHA = '215eb74ed6742bd1c3705501f2d4091de717e76dd2fff290737ba64aa1ecb2f7'
EVIDENCE_SHA = 'f5d8b0ab758dd6d09a42ccd174ec4a27edbbe00c36818a0929523bba11e45046'
KERNEL_SHA = '5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8'
KERNEL_NAME = 'kernel.development.vermeer-build.macho'
MEMBERS = {KERNEL_NAME, 'SHA256SUMS', 'build-report.json', 'crypto-hmac.json', 'symbols.txt'}
MAX_BYTES = 32 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def validate_archive(raw, zip_sha, kernel_sha):
    """Validate a bounded archive in memory before any filesystem mutation."""
    if sha(raw) != zip_sha:
        raise ValueError('platform archive SHA-256 mismatch')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            items = archive.infolist()
            if len(items) != len(MEMBERS) or {item.filename for item in items} != MEMBERS:
                raise ValueError('unexpected, missing or duplicate platform archive member')
            if sum(item.file_size for item in items) > MAX_BYTES:
                raise ValueError('platform archive expansion size exceeds limit')
            for item in items:
                if item.file_size > MAX_BYTES or item.file_size < 0:
                    raise ValueError('platform member size exceeds limit')
                kind = stat.S_IFMT(item.external_attr >> 16)
                if item.is_dir() or kind not in (0, stat.S_IFREG):
                    raise ValueError('platform member must be a regular file')
                if item.flag_bits & 1:
                    raise ValueError('encrypted platform member rejected')
            files = {item.filename: archive.read(item) for item in items}
            if any(len(files[item.filename]) != item.file_size for item in items):
                raise ValueError('platform member size mismatch')
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        raise ValueError('invalid platform ZIP') from error
    if sha(files[KERNEL_NAME]) != kernel_sha:
        raise ValueError('kernel SHA-256 mismatch')
    manifest = (kernel_sha + '  ' + KERNEL_NAME + '\n').encode('ascii')
    if files['SHA256SUMS'] != manifest:
        raise ValueError('kernel manifest does not match pinned kernel')
    return files


def restore(bundle, output):
    """Restore the exact pinned pair; reject existing output, including symlinks."""
    bundle, output = Path(bundle), Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError('kernel output already exists; overwrite refused')
    platform = (bundle / 'platform.zip').read_bytes()
    evidence = (bundle / 'evidence.zip').read_bytes()
    if sha(evidence) != EVIDENCE_SHA:
        raise ValueError('evidence SHA-256 mismatch')
    files = validate_archive(platform, PLATFORM_SHA, KERNEL_SHA)
    # All validation precedes output creation. mkdir is exclusive, so another
    # process creating the destination after the first check is not overwritten.
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    for name, data in files.items():
        with (output / name).open('xb') as target:
            target.write(data)
    return {
        'source_run_id': 40518851995,
        'platform_sha256': PLATFORM_SHA,
        'evidence_sha256': EVIDENCE_SHA,
        'kernel_sha256': KERNEL_SHA,
        'restored_files': len(files),
        'source': 'preserved original public artifact ZIP bytes in this Git checkout',
        'reproducible_compilation_verified': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'pinned-inputs/40518851995')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        report = restore(args.bundle, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
