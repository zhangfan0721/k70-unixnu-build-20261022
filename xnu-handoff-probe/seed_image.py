#!/usr/bin/env python3
"""Create a public zero-seed template or privately seed it for one local boot."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import struct

PAYLOAD_BYTES = 21434928
PAYLOAD_SHA = '83af881886b623abe76f8d9be983ede973faccb6c13e7662fee20cc951fbc803'
TRAILER_BYTES = 112
PAGE = 4096


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspect_image(image):
    if not PAGE <= len(image) <= 64 * 1024 * 1024 or image[:8] != b'ANDROID!':
        raise ValueError('Not a bounded Android boot image')
    ks, ka, rs, ra, second, _, tags, page, version, _ = struct.unpack_from('<10I', image, 8)
    if (ka, ra, second, tags, page, version) != (0x8000, 0xaa000000, 0, 0x1e00000, PAGE, 0):
        raise ValueError('Unexpected boot header/load addresses')
    if not 0 < ks <= 4 * 1024 * 1024 or rs not in (PAYLOAD_BYTES, PAYLOAD_BYTES + TRAILER_BYTES):
        raise ValueError('Unexpected firmware/payload size')
    at = PAGE * (1 + (ks + PAGE - 1) // PAGE)
    end = at + rs
    if end > len(image) or ((end + PAGE - 1) // PAGE) * PAGE != len(image):
        raise ValueError('Truncated or extended image')
    if any(image[PAGE + ks:at]) or any(image[end:]):
        raise ValueError('Nonzero image padding')
    if digest(image[at:at + PAYLOAD_BYTES]) != PAYLOAD_SHA:
        raise ValueError('Pinned kernel envelope differs')
    return dict(ramdisk_offset=at, ramdisk_bytes=rs, seed_offset=at + PAYLOAD_BYTES,
                image_bytes=len(image), image_sha256=digest(image),
                ramdisk_sha256=digest(image[at:end]), kernel_bytes=ks)


def template_image(image):
    info = inspect_image(image)
    if info['ramdisk_bytes'] != PAYLOAD_BYTES:
        raise ValueError('Expected unextended preflight image')
    at = info['seed_offset']
    result = bytearray(image[:at] + bytes(TRAILER_BYTES))
    result.extend(bytes(-len(result) % PAGE))
    struct.pack_into('<I', result, 16, PAYLOAD_BYTES + TRAILER_BYTES)
    inspect_image(result)
    return bytes(result)


def verify_seeded_image(image):
    info = inspect_image(image)
    if info['ramdisk_bytes'] != PAYLOAD_BYTES + TRAILER_BYTES:
        raise ValueError('No seed trailer')
    at = info['seed_offset']; trailer = image[at:at + TRAILER_BYTES]
    if trailer[:16] != struct.pack('<8sII', b'K70SEED1', 1, 64):
        raise ValueError('Wrong seed metadata; public template is not boot ready')
    seed = trailer[16:80]
    if not any(seed) or hashlib.sha256(trailer[:80]).digest() != trailer[80:]:
        raise ValueError('Seed trailer integrity/shape failure')
    return dict(info, seed_sha256=digest(seed), trailer_sha256=digest(trailer),
                seed_source='not attested by image; transport integrity only',
                host_generation_attested=False)


def inject_seed(image, expected_sha):
    if not re.fullmatch('[0-9a-f]{64}', expected_sha) or digest(image) != expected_sha:
        raise ValueError('Input image SHA-256 mismatch')
    info = inspect_image(image); at = info['seed_offset']
    if info['ramdisk_bytes'] != PAYLOAD_BYTES + TRAILER_BYTES or image[at:at + TRAILER_BYTES] != bytes(TRAILER_BYTES):
        raise ValueError('Expected public zero-seed template; repeated injection refused')
    seed = secrets.token_bytes(64)
    if not any(seed): raise ValueError('Unexpected all-zero random seed')
    trailer = struct.pack('<8sII64s', b'K70SEED1', 1, 64, seed)
    trailer += hashlib.sha256(trailer).digest()
    result = image[:at] + trailer + image[at + TRAILER_BYTES:]
    if result[:at] != image[:at] or result[at + TRAILER_BYTES:] != image[at + TRAILER_BYTES:]:
        raise ValueError('Changes escaped seed reservation')
    report = verify_seeded_image(result)
    report.update(input_image_sha256=expected_sha, changed_region_bytes=112,
                  seed_source='local PC OS CSPRNG generation invoked for this preparation',
                  host_generation_attested=True,
                  prepared_at_utc=datetime.now(timezone.utc).isoformat(),
                  policy='local-only, freshly prepare from the public template before each boot')
    return result, report


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('mode', choices=['template', 'inject', 'verify'])
    cli.add_argument('--input', type=Path, required=True)
    cli.add_argument('--out', type=Path)
    cli.add_argument('--report', type=Path)
    cli.add_argument('--expected-sha')
    args = cli.parse_args(); image = args.input.read_bytes()
    if args.mode == 'verify':
        print(json.dumps(verify_seeded_image(image), indent=2))
        return
    if args.out is None or args.report is None:
        cli.error('--out and --report are required')
    if args.out.exists() or args.report.exists():
        raise ValueError('Refusing to overwrite an existing image/report')
    if args.mode == 'template':
        result = template_image(image)
        report = dict(inspect_image(result), requires_private_seed=True,
                      kernel_executed=False, mode='handoff-data-no-jump-template')
    else:
        if args.expected_sha is None: cli.error('--expected-sha is required for private injection')
        result, report = inject_seed(image, args.expected_sha)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('xb') as output: output.write(result)
    with args.report.open('x') as output: output.write(json.dumps(report, indent=2) + '\n')
    print('Template written; private seed required.' if args.mode == 'template' else
          'Fresh local seed injected; only the reserved 112 bytes changed. Seed not printed.')


if __name__ == '__main__': main()
