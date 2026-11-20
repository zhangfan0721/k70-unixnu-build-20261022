#!/usr/bin/env python3
"""Generate an isolated full-window data check from hash-pinned preflight."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
APP_SHA = '066c35390a8e6b4c506b6e021bcd38355357dbf182c4e228c844e7acd249e155'
HOST_SHA = '360131bdfb55dcae3ca69563d92ca9fce8578a6f0d44bdd542008390ac739c03'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def normalized(path):
    return path.read_bytes().replace(b'\r\n', b'\n')


def templates():
    source = HERE.parent / 'xnu-handoff/handoff.py'
    if hashlib.sha256(normalized(source)).hexdigest() != HOST_SHA:
        raise ValueError('Reviewed host handoff source changed')
    host = module('reviewed_host_handoff', source)
    seed = b'S' * 64
    tree = host.make_tree(host.BASE, host.WINDOW, seed)
    layout = host.plan_layout(host.KERNEL['span'], host.KERNEL['vm_base'], host.KERNEL['entry_offset'], len(tree))
    args = host.make_args(layout, len(tree), host.GOP, '-v')
    host.verify_candidate(args, tree, host.KERNEL)
    if tree.count(seed) != 1 or len(tree) != 1724:
        raise ValueError('Unexpected seed slot or ADT size')
    offset = tree.index(seed); tree = tree[:offset] + bytes(64) + tree[offset + 64:]
    def array(name, data):
        return f'STATIC CONST UINT8 {name}[{len(data)}] = {{' + ','.join(f'0x{x:02x}' for x in data) + '};\n'
    header = '// Generated from the reviewed bounded host profile. Seed slot is deliberately zero.\n'
    header += f'#define K70_DATA_SEED_OFFSET {offset}U\n'
    for name, data in [('mHandoffArgs', args), ('mHandoffTreeTemplate', tree),
                       ('mHandoffArgsHash', hashlib.sha256(args).digest()),
                       ('mHandoffTreeHash', hashlib.sha256(tree).digest())]:
        header += array(name, data)
    report = dict(layout, seed_offset=offset, args_bytes=len(args), tree_bytes=len(tree),
                  args_sha256=hashlib.sha256(args).hexdigest(), zero_seed_tree_sha256=hashlib.sha256(tree).hexdigest(),
                  requires_private_seed=True, runtime_tested=False)
    return header, report


def prepare(root, dtb, kernel, payload):
    old_app = HERE.parent / 'xnu-preflight/Preflight.c'
    if hashlib.sha256(normalized(old_app)).hexdigest() != APP_SHA:
        raise ValueError('Photo-proven preflight source changed')
    header, handoff = templates()
    sys.path.insert(0, str(HERE.parent / 'xnu-preflight'))
    base = module('pinned_preflight_prepare', HERE.parent / 'xnu-preflight/prepare.py')
    report = base.prepare(root, dtb, kernel, payload)
    app = root / 'Platforms/Xiaomi/vermeerProbePkg/Probe'
    text = (app / 'Preflight.c').read_text()
    replacements = [
        ('#include "ExpectedPayload.h"', '#include "ExpectedPayload.h"\n#include "Handoff.h"'),
        ('K70 XNU LOAD PREFLIGHT - NO JUMP', 'K70 HANDOFF DATA CHECK - NO JUMP'),
        ('PayloadBytes != 128 + K70_EXPECTED_KERNEL_BYTES',
         'PayloadBytes != 128 + K70_EXPECTED_KERNEL_BYTES + K70_SEED_TRAILER_BYTES'),
        ('K70InspectPayload(Payload, (UINTN)PayloadBytes,',
         'K70InspectPayload(Payload, (UINTN)PayloadBytes - K70_SEED_TRAILER_BYTES,'),
        ('Pages = EFI_SIZE_TO_PAGES((UINTN)Plan.Span);', 'Pages = EFI_SIZE_TO_PAGES(K70_HANDOFF_WINDOW);'),
        ('Destination, Plan.Span, Status));', 'Destination, K70_HANDOFF_WINDOW, Status));'),
    ]
    old_tail = ('  DEBUG((DEBUG_ERROR, "PREFLIGHT PASS - KERNEL JUMP DISABLED\\nboot_args / ADT handoff: NOT BUILT\\nMMU/cache/GIC unchanged; services active\\n"));\n'
                '  Status = EFI_SUCCESS;')
    new_tail = ('  Status = K70PrepareHandoff(Destination, EFI_PAGES_TO_SIZE(Pages), Plan.Span,\n'
                '                             Payload + 128 + K70_EXPECTED_KERNEL_BYTES, K70_SEED_TRAILER_BYTES);')
    replacements.append((old_tail, new_tail))
    for before, after in replacements:
        if text.count(before) != 1: raise ValueError('Preflight integration anchor changed: ' + before[:60])
        text = text.replace(before, after)
    (app / 'Preflight.c').write_text(text, newline='\n')
    for name in ['Handoff.c', 'Handoff.h', 'HandoffCore.c', 'HandoffCore.h']:
        shutil.copy2(HERE / name, app / name)
    (app / 'HandoffTemplates.h').write_text(header, newline='\n')
    inf = app / 'VermeerProbe.inf'; text = inf.read_text()
    text = text.replace('  ExpectedPayload.h', '  ExpectedPayload.h\n  Handoff.c\n  Handoff.h\n  HandoffCore.c\n  HandoffCore.h\n  HandoffTemplates.h')
    inf.write_text(text, newline='\n')
    report.update(mode='handoff-data-no-jump', handoff=handoff, kernel_executed=False,
                  boot_args_built=False, adt_handoff_built=False, private_seed_required=True)
    return report


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for key in ['uefi', 'dtb', 'kernel', 'payload']: cli.add_argument('--' + key, type=Path, required=True)
    args = cli.parse_args()
    try:
        report = prepare(args.uefi.resolve(), args.dtb.resolve(), args.kernel.resolve(), args.payload.resolve())
    except (ValueError, OSError) as error: cli.exit(1, str(error) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
