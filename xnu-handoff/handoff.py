#!/usr/bin/env python3
"""Build/verify local K70 handoff data. This program cannot execute a kernel."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import struct
import sys

BASE = 0x880004000
WINDOW = 0x10000000
LIMIT = 0x8B9D00000
MAX64 = (1 << 64) - 1
KERNEL = {
    'kernel_sha256': '5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8',
    'vm_base': 0xFFFFFFF007004000, 'span': 0x1544000, 'entry_offset': 0x3F5488,
}
GOP = dict(base=0xB8000000, size=0x1194000, width=1440, height=3200,
           stride=1440, format=1)
ARGS = struct.Struct('<HHIQQQQ6QIIQI1024sIQQ')


def checked_end(base, size):
    if type(base) is not int or type(size) is not int or not 0 <= base <= MAX64 or not 0 < size <= MAX64 - base:
        raise ValueError('Invalid or overflowing address range')
    return base + size


def align(value, alignment):
    result = (value + alignment - 1) & -alignment
    if result > MAX64:
        raise ValueError('Alignment overflow')
    return result


def plan_layout(span, vm_base, entry_offset, tree_bytes, *, base=BASE, window=WINDOW):
    if (span, vm_base, entry_offset) != (KERNEL['span'], KERNEL['vm_base'], KERNEL['entry_offset']):
        raise ValueError('Not the pinned kernel layout')
    if base != BASE or window != WINDOW or not 0 < tree_bytes <= 65536:
        raise ValueError('Not the bounded diagnostic window/tree profile')
    end = checked_end(base, window)
    checked_end(vm_base, window)
    if end > LIMIT or base % 0x200000 != vm_base % 0x200000:
        raise ValueError('Window reservation/alignment mismatch')
    args_pa = align(checked_end(base, span), 16384)
    tree_pa = checked_end(args_pa, 4096)
    top = align(checked_end(tree_pa, tree_bytes), 16384)
    if top > end - 0x200000:
        raise ValueError('No bootstrap spare tail')
    return dict(base=base, window_bytes=window, window_end=end, vm_base=vm_base,
                args_pa=args_pa, tree_pa=tree_pa, tree_va=vm_base + tree_pa - base,
                top_pa=top, entry_pa=base + entry_offset, tree_bytes=tree_bytes)


def _node(name, properties=(), children=()):
    props = [('name', name.encode('ascii') + b'\0'), *properties]
    return struct.pack('<II', len(props), len(children)) + b''.join(
        struct.pack('<32sI', key.encode('ascii'), len(value)) + value + bytes(-len(value) % 4)
        for key, value in props) + b''.join(children)


def make_tree(base, size, seed):
    if base != BASE or size != WINDOW:
        raise ValueError('Tree memory must describe only the planned diagnostic window')
    if not isinstance(seed, bytes) or len(seed) != 64 or not any(seed):
        raise ValueError('A nonzero 64-byte seed is required; entropy quality is not inferred')
    u32 = lambda x: struct.pack('<I', x)
    u64 = lambda x: struct.pack('<Q', x)
    return _node('device-tree', [('model', b'vermeer-bringup\0'),
                 ('compatible', b'xiaomi,vermeer\0qcom,sm8550\0'),
                 ('#address-cells', u32(2)), ('#size-cells', u32(2))], [
        _node('chosen', [('random-seed', seed), ('dram-base', u64(base)),
              ('dram-size', u64(size)), ('darwinboot-memory-size', u64(size)),
              ('diagnostic-memory-scope', b'planned-owned-window-only\0')],
              [_node('memory-map')]),
        _node('cpus', children=[_node('cpu0', [('state', b'running\0'),
              ('reg', u32(0)), ('device_type', b'cpu\0'),
              ('compatible', b'arm,cortex-a510\0'), ('timebase-frequency', u32(19200000))])]),
        _node('arm-io', [('device_type', b'arm-io\0'), ('#address-cells', u32(2)),
              ('#size-cells', u32(2)), ('ranges', struct.pack('<QQQ', 0, 0x17000000, 0x08000000))],
              [_node('intc', [('compatible', b'arm,gic-v3\0'),
               ('reg', struct.pack('<4Q', 0x100000, 0x10000, 0x180000, 0x200000)),
               ('redistributor-stride', u64(0x40000))])]),
        _node('defaults', [('sleep-disabled', u32(1))]), _node('options'),
        _node('product', [('product-name', b'Redmi K70\0'), ('model', b'xiaomi,vermeer\0')]),
    ])


def parse_tree(blob):
    if not 8 <= len(blob) <= 65536:
        raise ValueError('Invalid ADT size')
    offset, nodes, properties = 0, 0, 0
    result = {}

    def read(count):
        nonlocal offset
        if count < 0 or count > len(blob) - offset:
            raise ValueError('Truncated ADT')
        value = blob[offset:offset + count]; offset += count
        return value

    def text(value):
        if not value or b'\0' not in value:
            raise ValueError('Unterminated ADT name')
        name, padding = value.split(b'\0', 1)
        if any(padding) or not re.fullmatch(rb'[A-Za-z0-9_,.#-]{1,31}', name):
            raise ValueError('Invalid ADT name')
        return name.decode('ascii')

    def walk(parent, depth):
        nonlocal nodes, properties
        if depth > 16:
            raise ValueError('ADT too deep')
        nodes += 1
        nprops, nchildren = struct.unpack('<II', read(8))
        properties += nprops
        if nodes > 64 or nprops == 0 or properties > 256 or nchildren > 64:
            raise ValueError('ADT count limit')
        props = {}
        for _ in range(nprops):
            key = text(read(32)); size = struct.unpack('<I', read(4))[0]
            if key in props:
                raise ValueError('Duplicate ADT property')
            props[key] = read(size)
            if any(read(-size % 4)):
                raise ValueError('Nonzero ADT padding')
        name = text(props.get('name', b''))
        path = '/' if depth == 0 else parent.rstrip('/') + '/' + name
        if path in result:
            raise ValueError('Duplicate ADT sibling')
        result[path] = props
        for _ in range(nchildren): walk(path, depth + 1)

    walk('', 0)
    if offset != len(blob):
        raise ValueError('Trailing ADT bytes')
    return result


def _video(video):
    if video != GOP:
        raise ValueError('GOP differs from the verified K70 profile')
    row = video['stride'] * 4
    needed = row * video['height']
    checked_end(video['base'], video['size'])
    if not video['width'] or not video['height'] or video['stride'] < video['width'] or needed > video['size']:
        raise ValueError('Invalid GOP extent')
    return (video['base'], 1, row, video['width'], video['height'], 32)


def make_args(layout, tree_length, video, command):
    expected = plan_layout(KERNEL['span'], KERNEL['vm_base'], KERNEL['entry_offset'], tree_length)
    if layout != expected or command != '-v':
        raise ValueError('Unexpected layout or command line')
    line = command.encode('ascii') + b'\0'
    return ARGS.pack(2, 2, 0, layout['vm_base'], layout['base'], layout['window_bytes'],
                     layout['top_pa'], *_video(video), 0, 0, layout['tree_va'],
                     tree_length, line, 0, 0, layout['window_bytes'])


def verify_candidate(args, tree, kernel_report):
    if any(kernel_report.get(k) != v for k, v in KERNEL.items()):
        raise ValueError('Kernel profile mismatch')
    if len(args) != 0x480:
        raise ValueError('Wrong boot_args size')
    parsed = parse_tree(tree)
    try:
        seed = parsed['/chosen']['random-seed']
    except KeyError as error:
        raise ValueError('Missing chosen seed') from error
    if tree != make_tree(BASE, WINDOW, seed):
        raise ValueError('ADT differs from the bounded K70 diagnostic profile')
    layout = plan_layout(KERNEL['span'], KERNEL['vm_base'], KERNEL['entry_offset'], len(tree))
    # Check on-disk fields independently of make_args' pack format.
    fields = [(0, '<HH', (2, 2)), (8, '<4Q', (KERNEL['vm_base'], BASE, WINDOW, layout['top_pa'])),
              (0x28, '<6Q', _video(GOP)), (0x60, '<QI', (layout['tree_va'], len(tree))),
              (0x470, '<QQ', (0, WINDOW))]
    if any(struct.unpack_from(fmt, args, offset) != value for offset, fmt, value in fields):
        raise ValueError('Boot args field/range mismatch')
    if any(args[4:8]) or any(args[0x58:0x60]) or any(args[0x46c:0x470]):
        raise ValueError('Nonzero reserved boot args fields')
    if args[0x6c:0x46c] != b'-v\0' + bytes(1021):
        raise ValueError('Unexpected boot command line')
    return dict(layout, kernel=dict(KERNEL), abi_bytes=0x480, page_bytes=4096,
                tree_nodes=len(parsed), allocation_verified=False, execution_ready=False,
                kernel_executed=False, seed_scope='local host candidate; regenerate during future firmware boot',
                remaining=['Allocate and revalidate the entire window on the phone',
                           'Generate fresh entropy in that firmware boot',
                           'Verify entry code, owned ranges and executable attributes',
                           'Prove cache/MMU/ExitBootServices sequence and an early checkpoint'])


def build_candidate(kernel, seed=None):
    if hashlib.sha256(kernel).hexdigest() != KERNEL['kernel_sha256']:
        raise ValueError('Wrong kernel SHA-256')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'xnu-preflight'))
    from payload import materialize
    plan, mapped = materialize(kernel)
    if (plan.VmBase, plan.Span, plan.EntryOffset) != (KERNEL['vm_base'], KERNEL['span'], KERNEL['entry_offset']):
        raise ValueError('Actual Mach-O layout mismatch')
    if hashlib.sha256(mapped).hexdigest() != '60f20ad852e755261c8f42545a99d2fae092c9c83bbaf1064568c37dccd88442':
        raise ValueError('Materialized kernel mismatch')
    tree = make_tree(BASE, WINDOW, secrets.token_bytes(64) if seed is None else seed)
    layout = plan_layout(plan.Span, plan.VmBase, plan.EntryOffset, len(tree))
    args = make_args(layout, len(tree), GOP, '-v')
    return args, tree, verify_candidate(args, tree, KERNEL)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest='mode', required=True)
    build = sub.add_parser('build'); build.add_argument('--kernel', type=Path, required=True)
    build.add_argument('--out', type=Path, required=True)
    check = sub.add_parser('verify'); check.add_argument('directory', type=Path)
    opts = cli.parse_args()
    if opts.mode == 'build':
        args, tree, report = build_candidate(opts.kernel.read_bytes())
        # A new dedicated directory prevents silently replacing a candidate.
        opts.out.mkdir(parents=True, exist_ok=False)
        (opts.out / 'boot-args.bin').write_bytes(args)
        (opts.out / 'device-tree.adt').write_bytes(tree)
        (opts.out / 'layout.json').write_text(json.dumps(report, indent=2) + '\n')
        names = ['boot-args.bin', 'device-tree.adt', 'layout.json']
        (opts.out / 'SHA256SUMS').write_text(''.join(
            hashlib.sha256((opts.out / n).read_bytes()).hexdigest() + '  ' + n + '\n' for n in names))
        print('Local candidate written; allocation and execution remain unverified.')
    else:
        folder = opts.directory
        expected_names = {'boot-args.bin', 'device-tree.adt', 'layout.json'}
        lines = (folder / 'SHA256SUMS').read_text().splitlines()
        records = [line.split('  ', 1) for line in lines]
        if len(records) != 3 or any(len(x) != 2 for x in records) or {x[1] for x in records} != expected_names:
            raise ValueError('Invalid checksum manifest')
        for digest, name in records:
            if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
                raise ValueError('Candidate checksum mismatch')
        prior = json.loads((folder / 'layout.json').read_text())
        report = verify_candidate((folder / 'boot-args.bin').read_bytes(),
                                  (folder / 'device-tree.adt').read_bytes(), prior['kernel'])
        if report != prior:
            raise ValueError('Candidate layout report mismatch')
        print('Candidate checksum, ABI fields, tree and address relations verified; no execution.')


if __name__ == '__main__':
    main()
