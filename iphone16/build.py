"""Compile the single Darwin22 K70 integration gate; never operates a device."""
import argparse
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import platform
import os
import shutil
import struct
import subprocess
import sys
import tomllib
from check_sources import check as check_source_inputs

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('iphone16_prepare', HERE / 'prepare.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
KERNEL = 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped'
IIG_VERSION = 'DriverKit-286'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_kernel(path):
    data = path.read_bytes()
    if len(data) < 32 or struct.unpack_from('<4I', data) != (0xfeedfacf, 0x100000c, 0, 2):
        raise ValueError('Expected ordinary ARM64 MH_EXECUTE')
    ncmds, size = struct.unpack_from('<2I', data, 16)
    end, offset, entry, build = 32 + size, 32, False, None
    if end > len(data):
        raise ValueError('Truncated load commands')
    segments = []
    for _ in range(ncmds):
        if offset + 8 > end:
            raise ValueError('Truncated load command')
        cmd, length = struct.unpack_from('<II', data, offset)
        if length < 8 or offset + length > end:
            raise ValueError('Invalid load command size')
        if cmd == 0x32:
            if length < 24:
                raise ValueError('Truncated build version')
            build = struct.unpack_from('<3I', data, offset + 8)
        if cmd == 5:
            entry = True
        if cmd == 0x19:
            if length < 72:
                raise ValueError('Truncated segment')
            name, va, vmsize, fileoff, filesize = struct.unpack_from('<16s4Q', data, offset + 8)
            if fileoff + filesize > len(data) or filesize > vmsize:
                raise ValueError('Invalid file-backed segment')
            segments.append({'name': name.rstrip(b'\0').decode(), 'va': hex(va), 'bytes': vmsize})
        offset += length
    if offset != end or not entry or not build or build[:2] != (2, 0x100000):
        raise ValueError('Expected iOS16 kernel with a UNIXTHREAD entry: ' + str(build))
    for name in ('_source_corecrypto14_bootstrap', '_source_pthread_bootstrap',
                 '_armdt_platform_configured', '_armcpu_registered', '_armcpu_gic_ready',
                 '_armcpu_timer_interrupts', '_k70_formal_cpu_online', '_k70_formal_thread_turn',
                 '_k70_cpu_start_phase', '_k70_first_irq_pc', '_k70_first_irq_cpsr', '_k70_first_irq_sp',
                 '_k70_flight_panic', '_k70_flight_wait', '_k70_flight_begin',
                 '_k70_flight_enter', '_k70_flight_leave', '_k70_flight_bind',
                 '_k70_formal_bootstrap', '_k70_formal_early_exception', '_vfs_getvfs_with_vfsops',
                 '_k70_ufs_readonly_qualify',
                 '_kalloc_sparse_prelink_index_version'):
        if name.encode() + b'\0' not in data:
            raise ValueError('Missing real integration symbol: ' + name)
    return {'sha256': digest(path), 'bytes': len(data), 'platform': build[0],
            'minimum': hex(build[1]), 'sdk': hex(build[2]), 'segments': segments,
            'original_component_abi_verified': False, 'hardware_boot_tested': False,
            'root_mounted': False, 'userspace_started': False}


def verify_iorpc(tree, output):
    original = tree / 'refer/xnu/iokit/IOKit/IORPC.h'
    header = tree / '.cache/xnu-work/iokit/IOKit/IORPC.h'
    if header.read_bytes() != original.read_bytes():
        raise ValueError('IORPC header differs from the original fixed XNU22 ABI')
    objroot = tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'
    records = []
    for path in (objroot / 'iokit/DEVELOPMENT').glob('IOService*.json'):
        record = json.loads(path.read_text().strip().rstrip(','))
        if Path(record.get('file', '')).name == 'IOService.iig.cpp':
            records.append(record)
    if len(records) != 1:
        raise ValueError('Expected one actual IOService generated-code compile record')
    record = records[0]
    # Configuration builds generate another DriverKit tree below DEVELOPMENT;
    # the compiler record, not the installhdrs output path, is authoritative.
    source = (Path(record['directory']) / record['file']).resolve()
    text = source.read_text()
    if 'kernelContent' in text or 'IORPCMessageFromMach' not in text:
        raise ValueError('Generator did not preserve legacy IORPC message handling')
    fixture = output / 'iorpc-layout.cpp'
    fixture.write_text('#include <IOKit/IORPC.h>\nstatic_assert(sizeof(IORPC) == 24);\n'
                       'static_assert(__builtin_offsetof(IORPC, sendSize) == 16);\n'
                       'static_assert(__builtin_offsetof(IORPC, replySize) == 20);\n')
    command, index = [], 0
    while index < len(record['arguments']):
        value = record['arguments'][index]
        if value == record['file']:
            command.append(str(fixture))
        elif value == '-o':
            command.extend(['-o', str(output / 'iorpc-layout.o')])
            index += 1
        else:
            command.append(value)
        index += 1
    (output / 'iorpc-layout-command.json').write_text(json.dumps(command, indent=2) + '\n')
    subprocess.run(command, cwd=record['directory'], check=True)
    return {'original_header_sha256': digest(header), 'generated_ioservice_sha256': digest(source),
            'layout_bytes_asserted': 24, 'legacy_message_handling': True,
            'original_component_runtime_tested': False}


def check(core, device, font):
    if adapter.git(core, 'rev-parse', 'HEAD') != adapter.CORE or adapter.git(core, 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Use the immutable pinned UniXNU checkout')
    if adapter.git(device, 'rev-parse', 'HEAD') != adapter.DEVICE:
        raise ValueError('Unexpected source-device reference')
    feeds = tomllib.loads((HERE / 'device/feeds.toml').read_text())['source']
    if next(x for x in feeds if x['name'] == 'xnu')['commit'] != adapter.XNU:
        raise ValueError('XNU pin mismatch')
    if digest(font) != 'd2a3687db67b069f4e34a961e17fd28b0242986e3fa8dd8a7545cab70834fa8e':
        raise ValueError('Unexpected baseline font')
    board = tomllib.loads((HERE / 'device/board.toml').read_text())
    if set(board) != {'board', 'kernel'} or set(board['kernel']) != {'defconfig', 'archives'}:
        raise ValueError('This gate must not include prelink, firmware, storage or userdata actions')
    return feeds


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--core', type=Path, required=True)
    p.add_argument('--source-device', type=Path, required=True)
    p.add_argument('--font', type=Path, required=True)
    p.add_argument('--out', type=Path, default=Path('out16'))
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--check', action='store_true')
    args = p.parse_args()
    core, device, font = args.core.resolve(), args.source_device.resolve(), args.font.resolve()
    feeds = check(core, device, font)
    sys.path.insert(0, str(core / 'scripts'))
    cli = importlib.import_module('unixnu.cli')
    config = importlib.import_module('unixnu.config')
    kernel = importlib.import_module('unixnu.kernel')
    parsed = config.parse_config((HERE / 'device/configs/vermeer16_defconfig').read_text())
    required = {'XNU_SOURCE_CORECRYPTO14', 'XNU_SOURCE_PTHREAD', 'XNU_ARM_DT_PLATFORM',
                'XNU_ARMCPU', 'XNU_NATIVE_ARCH_TIMER', 'XNU_DT_PANIC_REGION'}
    if {k for k, v in parsed.items() if v is True} != required or parsed.get('XNU_CRYPTO_BOOTSTRAP') != 'source':
        raise ValueError('Unexpected integration configuration')
    if args.check:
        print('Pinned Darwin22 source-only integration configuration verified; no boot claim')
        return
    if platform.system() != 'Darwin' or args.jobs < 1:
        raise ValueError('Full build requires macOS/Xcode and positive jobs')
    for tool in ('clang', 'mig'):
        subprocess.run(['xcrun', '--sdk', 'iphoneos', '--find', tool], check=True)
    iig = os.environ.get('IIG') or subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--find', 'iig'], text=True).strip()
    iig_version = subprocess.check_output([iig, '--version'], text=True).strip()
    if iig_version != IIG_VERSION:
        raise ValueError('Use the qualified legacy IIG generator: ' + iig_version)
    options = cli.parser().parse_args(['build', 'kernel', '-D', str(HERE / 'device'),
        '--out', str(args.out.resolve()), '-j', str(args.jobs)])
    ctx = config.Context(options)
    ctx.work.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / 'device/configs/vermeer16_defconfig', ctx.config_path)
    ctx.config = parsed
    modules = cli.prepare(ctx, ['kernel'])
    if adapter.git(ctx.tree / 'refer/xnu', 'rev-parse', 'HEAD') != adapter.XNU:
        raise ValueError('Resolved XNU source differs from requested Darwin22 pin')
    report = adapter.prepare(core, device, ctx.tree, font)
    (ctx.tree / '.cache/iphone16-patch-report.json').write_text(json.dumps(report, indent=2) + '\n')
    presence = check_source_inputs(ctx.tree / 'refer/xnu', ctx.tree / '.cache/iphone16-patch-source')
    (ctx.tree / '.cache/iphone16-source-presence.json').write_text(json.dumps(presence, indent=2) + '\n')
    if presence['missing'] or not presence['kpc_enabled'] or not presence['kperf_enabled']:
        raise ValueError('Selected configuration requires unavailable source inputs: ' + str(presence))
    flags = {}
    try:
        kernel.build(ctx, modules)
    finally:
        # Preserve the actual generated target flags even if compilation fails.
        objroot = ctx.tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'
        for name in ('.CFLAGS', '.LDFLAGS'):
            path = objroot / name
            if path.is_file():
                flags[name] = path.read_text().rstrip('\0\n')
        (ctx.work / 'actual-target-flags.json').write_text(json.dumps(flags, indent=2) + '\n')
    if set(flags) != {'.CFLAGS', '.LDFLAGS'} or any(
            '-miphoneos-version-min=16.0' not in value or '-DXNU_TARGET_OS_OSX' in value
            for value in flags.values()) or '-DXNU_TARGET_OS_IOS' not in flags['.CFLAGS']:
        raise ValueError('Actual compile/link flags do not identify the iOS16 target')
    source = ctx.tree / KERNEL
    report = verify_kernel(source) | {'unixnu': adapter.CORE, 'xnu': adapter.XNU,
        'source_device': adapter.DEVICE, 'feeds': feeds, 'configuration': parsed,
        'page_bytes': 4096, 'prelinked': False, 'source_presence': presence}
    output = ctx.work / 'kernel'
    output.mkdir()
    report['iorpc'] = verify_iorpc(ctx.tree, output)
    report['iig_version'] = iig_version
    target = output / 'kernel.development.vermeer16.macho'
    shutil.copy2(source, target)
    seal = source.with_suffix(source.suffix + '.crypto-hmac.json')
    if json.loads(seal.read_text())['kernel_sha256'] != report['sha256']:
        raise ValueError('Crypto HMAC report does not identify the final kernel')
    shutil.copy2(seal, output / 'crypto-hmac.json')
    with (output / 'symbols.txt').open('w') as stream:
        subprocess.run(['xcrun', 'nm', '-n', str(target)], stdout=stream, check=True)
    (output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    (output / 'SHA256SUMS').write_text(report['sha256'] + '  ' + target.name + '\n')
    print('Darwin22 integration built. Original component ABI, root and userspace remain unverified.')


if __name__ == '__main__':
    main()
