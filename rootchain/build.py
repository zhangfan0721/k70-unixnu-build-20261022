"""Prepare a LOCAL original-iPhone md0/HFS diagnostic candidate. No device I/O.

Apple inputs and resulting payloads stay local. This is an incremental formal
system root, not a claim that launchd dependencies or runtime ABI are qualified.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import plistlib
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


formal = module('rootchain_formal', HERE.parent / 'formal-xnu/payload.py')
sha = formal.sha
run = formal.run


def trust_bundle(args):
    """Same unchanged-module bundle contract as upstream build-original-system-trust.

    Select iPhone20H392 manifest inputs rather than the upstream iPad-only paths.
    """
    if args.out.exists():
        raise ValueError('Refusing to overwrite a trust bundle')
    manifest = plistlib.loads(args.manifest.read_bytes())
    if manifest['ProductBuildVersion'] != '20H392':
        raise ValueError('Require the selected original iPhone build')
    identity = next(i for i in manifest['BuildIdentities'] if
                    i['Info']['DeviceClass'] == 'd22ap' and i['Info']['RestoreBehavior'] == 'Erase')
    sys.path.insert(0, str(args.core / 'scripts'))
    from unixnu.ipsw import im4p_payload
    modules, records = [], {}
    for key, path in (('StaticTrustCache', args.static), ('Cryptex1,SystemTrustCache', args.system)):
        data = path.read_bytes()
        if hashlib.sha384(data).digest() != identity['Manifest'][key]['Digest']:
            raise ValueError('Original manifest digest mismatch: ' + key)
        raw = im4p_payload(data)
        if len(raw) < 24 or struct.unpack_from('<I', raw)[0] != 2:
            raise ValueError('Require original version2 trust module')
        count = struct.unpack_from('<I', raw, 20)[0]
        if len(raw) != 24 + count * 24:
            raise ValueError('Truncated trust entries')
        rows = [raw[24 + i * 24:48 + i * 24] for i in range(count)]
        if any(not 1 <= row[20] <= 4 for row in rows) or any(
                a[:20] >= b[:20] for a, b in zip(rows, rows[1:])):
            raise ValueError('Invalid original trust-entry ordering/type')
        modules.append(raw)
        records[key] = {'im4p_sha256': sha(path), 'module_sha256': hashlib.sha256(raw).hexdigest(),
                        'entries': count, 'manifest_sha384_verified': True}
    bundle = struct.pack('<3I', 2, 12, 12 + len(modules[0])) + b''.join(modules)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(bundle)
    records.update(bundle_sha256=sha(args.out), original_modules_modified=False, own_entries_added=False)
    args.out.with_suffix('.json').write_text(json.dumps(records, indent=2) + '\n')
    return records


def root_image(args):
    out = args.out.resolve()
    if out.exists():
        raise ValueError('Refusing to overwrite a root preparation')
    # These bytes are extracted from the verified OS member, never rebuilt or patched.
    names = ('sbin/launchd', 'usr/lib/dyld')
    pins = {'sbin/launchd': '12370e5ee35bf28ae479b6c4b4455f4f4693ab803e37c5eb3032537c18cac61c',
            'usr/lib/dyld': '5806834564fe6462ae981d0915d612b1eb2f6f168822b5d278bee56254933757'}
    inputs = args.system.resolve()
    for name in names:
        if not (inputs / name).is_file() or sha(inputs / name) != pins[name]:
            raise ValueError('Require verified unchanged original 20H392 input: ' + name)
    out.mkdir(parents=True)
    image = out / 'root.hfs'
    with image.open('xb') as stream:
        stream.truncate(128 << 20)
    run('/usr/sbin/mkfs.hfsplus', '-v', 'K70ROOT16', '-b', '4096', image)
    run(args.hfs_tool, image, 'chmod', '755', '/')
    with tempfile.TemporaryDirectory() as tmp:
        check = Path(tmp)
        for name in ('sbin', 'usr', 'usr/lib', 'dev', 'private', 'private/var',
                     'private/var/run', 'private/tmp', 'System', 'System/Library',
                     'System/Library/Caches', 'System/Library/Caches/com.apple.dyld'):
            run(args.hfs_tool, image, 'mkdir', '/' + name)
            run(args.hfs_tool, image, 'chmod', '755', '/' + name)
        for source, target in (('/private/var', '/var'), ('/private/tmp', '/tmp')):
            # libdmg-hfsplus takes link path first, target bytes second.
            run(args.hfs_tool, image, 'symlink', target, source)
            # The writer's extract command follows links; 7z reads their raw fork.
            link = subprocess.check_output(['7z', 'x', '-so', str(image), 'K70ROOT16' + target])
            if link != source.encode():
                raise ValueError('HFS symbolic-link readback failed: ' + target)
        records = {}
        for name in names:
            run(args.hfs_tool, image, 'add', inputs / name, '/' + name)
            run(args.hfs_tool, image, 'chmod', '755', '/' + name)
            readback = check / Path(name).name
            run(args.hfs_tool, image, 'extract', '/' + name, readback)
            if readback.read_bytes() != (inputs / name).read_bytes():
                raise ValueError('HFS original bytes mismatch: ' + name)
            records[name] = {'sha256': sha(readback), 'bytes': readback.stat().st_size}
        # Independently parse the actual filesystem, including catalog permissions.
        listing = subprocess.check_output(['7z', 'l', '-slt', str(image)], text=True)
        (out / 'filesystem-listing.txt').write_text(listing)
        for name in names:
            sections = [s for s in listing.split('\n\n') if 'Path = K70ROOT16/' + name + '\n' in s]
            if len(sections) != 1 or 'Mode = -rwxr-xr-x' not in sections[0]:
                raise ValueError('HFS executable mode readback failed: ' + name)
    record = {'schema': 1, 'root_sha256': sha(image), 'bytes': image.stat().st_size,
              'files': records, 'source_build': 'iPhone10,3/iPhone10,6 16.7.16 20H392',
              'carrier': 'native XNU md0; volatile HFS+ RAM root; no physical storage',
              'original_files_modified': False, 'runtime_qualified': False,
              'dependency_closure_complete': False,
              'known_missing': ['matching System Cryptex shared cache not embedded in this root',
                                'formal system initialization resources and services'],
              'expected_scope': 'observe HFS mount and real load_init_program failure or progress'}
    (out / 'root.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def pack(args):
    out = args.out.resolve()
    if out.exists():
        raise ValueError('Refusing to overwrite a candidate')
    kernel, root, trust = [getattr(args, name).resolve() for name in ('kernel', 'root', 'trust')]
    prelink = json.loads(args.prelink_report.read_text())
    storage_proof = json.loads(args.storage_proof.read_text())
    required_components = set(json.loads((HERE / 'inputs.json').read_text())['components'])
    if set(prelink['components']) != required_components or \
            storage_proof['candidate_sha256'] != sha(kernel) or \
            not storage_proof['rebased_constructor_and_start_pointers_checked'] or \
            not storage_proof['original_execution_bytes_preserved'] or \
            not storage_proof['sparse_header_index_checked'] or \
            not storage_proof.get('legacy_static_slide_extent_covers_all_segments', False):
        raise ValueError('Require the complete matched RAM-root storage group and real input proof')
    seal = json.loads(args.hmac.read_text())
    root_report = json.loads(args.root_report.read_text())
    loader_proof = json.loads(args.loader_proof.read_text())
    if prelink['candidate_sha256'] != sha(kernel) or seal['kernel_sha256'] != sha(kernel):
        raise ValueError('Prelink/source-HMAC identity mismatch')
    ufs_path = getattr(args, 'ufs_proof', None)
    ufs = json.loads(ufs_path.read_text()) if ufs_path else None
    if ufs_path and (not isinstance(ufs, dict) or ufs.get('kernel_sha256') != sha(kernel) or
                    not ufs.get('bounded_readonly_transport') or
                    not ufs.get('actual_iokit_ios16_record') or not ufs.get('linked_normal_bsd_entry')):
        raise ValueError('UFS qualification proof does not bind this actual kernel')
    if root_report['root_sha256'] != sha(root) or loader_proof['kernel_sha256'] != sha(kernel) or \
            loader_proof['trust_sha256'] != sha(trust) or not loader_proof['real_parsers_passed']:
        raise ValueError('Root/actual-loader proof identity mismatch')
    if kernel.stat().st_size >= 128 << 20 or root.stat().st_size % 4096:
        raise ValueError('DarwinBoot input size contract failed')
    # Parse real Mach-O segment commands; include zero-fill in the owned-window proof.
    data = kernel.read_bytes()
    if struct.unpack_from('<I', data)[0] != 0xfeedfacf:
        raise ValueError('Expected native ARM64 Mach-O')
    segments = []
    at = 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, size = struct.unpack_from('<II', data, at)
        if size < 8 or at + size > len(data):
            raise ValueError('Invalid load command')
        if cmd == 0x19:
            va, vs, fo, fs = struct.unpack_from('<QQQQ', data, at + 24)
            if fo + fs > len(data):
                raise ValueError('Truncated segment')
            if vs:
                segments.append((va, va + vs))
        at += size
    span = max(end for _, end in segments) - min(start for start, _ in segments)
    # Bound DT/args/alignment separately; reserve DarwinBoot's last 2MiB block.
    maximum_used = span + (1 << 20) + root.stat().st_size + trust.stat().st_size
    if maximum_used > (512 << 20) - (2 << 20):
        raise ValueError('Candidate exceeds the existing 512MiB owned window')
    firmware = args.firmware.resolve()
    fd = firmware / 'Build/vermeerFormalPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd'
    firmware_proof = formal.verify_firmware(firmware, fd)
    packer = module('rootchain_packer', args.uefi / 'tools/vermeer-zh/pack_boot.py')
    if fd.stat().st_size != packer.FD_SIZE:
        raise ValueError('Unexpected FD size')
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        payloads = stage / 'EFI/UniXNU/Payloads'
        payloads.mkdir(parents=True)
        for source, name in ((kernel, 'kernel.macho'), (root, 'root.hfs'),
                             (trust, 'kernel.macho.trustcache')):
            shutil.copy2(source, payloads / name)
        adt = payloads / 'kernel.macho.adt'
        run(sys.executable, args.board / 'scripts/make-vermeer-adt.py', '--output', adt,
            '--dram-size', '0x80000000', '--owned-memory-size', '0x20000000',
            '--cpu-regs', '0', '--unique-chip-id', '1', '--chip-id', '207',
            '--data-ramdisk', '--trust-cache')
        tree, identity_offset = formal.blank_identity(adt.read_bytes())
        adt.write_bytes(tree)
        parsed = formal.handoff.parse_tree(tree)
        for name in ('RAMDisk', 'TrustCache'):
            if parsed['/chosen/memory-map'][name] != bytes(16):
                raise ValueError('Nonzero handoff placeholder: ' + name)
        configuration = '''version = 1
[boot]
timeout = 5
default = "xnu16"
[kits]
autoload = false
[[entry]]
id = "xnu16"
title = "K70 iPhone16 HFS root-chain diagnostic"
type = "xnu"
path = "Payloads/kernel.macho"
initrd = "Payloads/root.hfs"
args = "-v serial=3 debug=0x14e kt_fixed_zones=120 armcpu-diagnostics=1 startup_debug=1 kextlog=0x10503e rd=md0 launchdsuffix=release"
'''
        (stage / 'EFI/UniXNU/unixnu.toml').write_text(configuration)
        volume = out / 'payload-template.img'
        env = dict(os.environ, MTOOLS_SKIP_CHECK='1', TZ='UTC')
        # aa000000..b6000000 stays below the DT's b8000000 splash reservation.
        # A 256MiB envelope would overlap that reservation, despite fitting FAT.
        run('mformat', '-C', '-F', '-T', str(192 * 2048), '-v', 'K70ROOT16',
            '-N', '4b373016', '-i', volume, '::', env=env)
        run('mcopy', '-i', volume, '-s', '-Q', stage / 'EFI', '::/', env=env)
        check = stage / 'readback'
        check.mkdir()
        run('mcopy', '-i', volume, '::/EFI/UniXNU/unixnu.toml', check / 'unixnu.toml', env=env)
        if (check / 'unixnu.toml').read_text() != configuration:
            raise ValueError('Actual boot configuration readback failed')
        for path in payloads.iterdir():
            run('mcopy', '-i', volume, '::/EFI/UniXNU/Payloads/' + path.name,
                check / path.name, env=env)
            if sha(check / path.name) != sha(path):
                raise ValueError('FAT readback mismatch: ' + path.name)
        dtb = firmware / 'Resources/DTBs/vermeerFormal.dtb'
        packer.verify_dtb(dtb)
        if 0xaa000000 + volume.stat().st_size > 0xb8000000:
            raise ValueError('Android ramdisk overlaps the verified splash reservation')
        shim = packer.compile_shim(args.uefi, stage, 'clang', 'llvm-objcopy', 'llvm-nm')
        combined = shim + fd.read_bytes()
        packed = stage / 'Image.gz-dtb'
        packed.write_bytes(gzip.compress(combined, mtime=0) + dtb.read_bytes())
        boot = out / 'K70-iPhone16-rootchain-TEMPLATE.img'
        run(sys.executable, args.uefi / 'Resources/Scripts/mkbootimg.py', '--kernel', packed,
            '--ramdisk', volume, '--base', '0', '--kernel_offset', '0x8000',
            '--ramdisk_offset', '0xaa000000', '--tags_offset', '0x1e00000',
            '--pagesize', '4096', '--header_version', '0', '-o', boot)
        sys.path.insert(0, str(HERE.parent / 'xnu-preflight'))
        verifier = module('rootchain_verify_boot', HERE.parent / 'xnu-preflight/pack_boot.py')
        proof = verifier.verify_image(boot.read_bytes(), combined, dtb.read_bytes(), volume.read_bytes())
        if boot.read_bytes()[576:608] != formal.boot_v0_id(boot.read_bytes()):
            raise ValueError('Android ID mismatch')
        metadata = {'schema': 1, 'integration_commit': subprocess.check_output(
            ['git', '-C', str(HERE.parent), 'rev-parse', 'HEAD'], text=True).strip(),
            'template_sha256': sha(boot), 'payload_sha256': sha(volume),
            'kernel_sha256': sha(kernel), 'root_sha256': sha(root), 'trust_sha256': sha(trust),
            'adt_sha256': sha(adt), 'adt_identity_offset': identity_offset,
            'identity_zero': True, 'random_seed_zero': True, 'personalization_required': True,
            'firmware': firmware_proof, 'boot': proof, 'kernel_virtual_span': span,
            'maximum_owned_window_use': maximum_used, 'owned_window_bytes': 512 << 20,
            'android_ramdisk_end': hex(0xaa000000 + volume.stat().st_size),
            'splash_reserved_base': '0xb8000000', 'splash_overlap': False,
            'assembly_source_sha256': sha(Path(__file__)),
            'native_kernel_sha256': prelink['native_sha256'], 'prelink_slide': prelink['slide'],
            'legacy_static_slide_extent_covers_all_segments': True,
            'root_dependency_closure_complete': root_report['dependency_closure_complete'],
            'actual_loader_parsers_passed': loader_proof['real_parsers_passed'],
            'hardware_tested': False, 'userspace_verified': False, 'ui_verified': False,
            'local_only': True, 'scope': 'new16 kernel/HFS initialization/md0 mount/init exec diagnostics',
            'security_policy_modified': False, 'physical_storage_drivers_added': bool(ufs)}
        if ufs:
            metadata.update(scope='iOS16 bounded read-only UFS capacity/GPT/SHA qualification; existing HFS/md0 carrier',
                kernel_source_commit=ufs['kernel_source_commit'],ufs_readonly_qualification=True,
                storage_writes_allowed=False,ufs_root_published=False,
                ufs_read_contract={'lun':0,'block_bytes':4096,'ranges':[[0,6],[61842427,5]]},
                ufs_hardware_read_verified=False,ufs_proof_sha256=sha(args.ufs_proof))
            metadata.update(SMMU_configuration_writes=ufs['scope']['smmu_configuration_writes'],
                hardware_dma_isolation=ufs['scope'].get('hardware_dma_isolation',False),
                SMMU_write_scope=ufs['scope'].get('smmu_write_scope','none'))
        (out / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
        (out / 'unixnu.toml').write_text(configuration)
        shutil.copy2(adt, out / 'kernel.macho.adt')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    trust = sub.add_parser('trust')
    for name in ('manifest', 'static', 'system', 'core', 'out'):
        trust.add_argument('--' + name, type=Path, required=True)
    root = sub.add_parser('root')
    for name in ('system', 'hfs-tool', 'out'):
        root.add_argument('--' + name, type=Path, required=True)
    payload = sub.add_parser('pack')
    for name in ('kernel', 'root', 'trust', 'prelink-report', 'hmac', 'firmware', 'uefi', 'board',
                 'root-report', 'loader-proof', 'storage-proof', 'out'):
        payload.add_argument('--' + name, type=Path, required=True)
    payload.add_argument('--ufs-proof',type=Path)
    args = parser.parse_args()
    action = {'root': root_image, 'pack': pack, 'trust': trust_bundle}[args.command]
    print(json.dumps(action(args), indent=2))
