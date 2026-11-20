#!/usr/bin/env python3
"""Build bounded instrumented-entry blobs; original kernel input stays immutable."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PIN = '5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8'
BASE, ENTRY_OFFSET, PATCH_OFFSET = 0x880004000, 0x3f5488, 0x3f705c


def extract_elf(data):
    if len(data) < 64 or data[:16] != b'\x7fELF\x02\x01\x01' + bytes(9):
        raise ValueError('Not plain little-endian ELF64')
    kind, machine, version = struct.unpack_from('<HHI', data, 16)
    entry, _, shoff = struct.unpack_from('<QQQ', data, 24)
    ehsize, _, _, shsize, count, names = struct.unpack_from('<6H', data, 52)
    if (kind, machine, version, entry, ehsize, shsize) != (2, 183, 1, 0, 64, 64):
        raise ValueError('Unexpected ELF architecture/layout/entry')
    if not 1 < count < 64 or names >= count or shoff > len(data) - count * 64:
        raise ValueError('Section bounds')
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, shoff + i * 64) for i in range(count)]
    def contents(section):
        off, size = section[4:6]
        if off > len(data) or size > len(data) - off: raise ValueError('Section data bounds')
        return data[off:off + size]
    def string(table, at):
        if at >= len(table) or b'\0' not in table[at:]: raise ValueError('String bounds')
        return table[at:table.index(0, at)].decode('ascii')
    strings = contents(sections[names])
    text_index = None
    for i, section in enumerate(sections):
        name, kind, flags, address, off, size, link, info, alignment, entsize = section
        label = string(strings, name)
        if kind in (4, 9) and size: raise ValueError('Relocations forbidden')
        if flags & 2 and size:
            if label != '.text' or flags != 6 or kind != 1 or address != 0 or size > 4096 or size % 4:
                raise ValueError('Only bounded executable .text is allowed')
            if text_index is not None: raise ValueError('Duplicate .text')
            text_index = i
        if kind != 8: contents(section)
    if text_index is None: raise ValueError('No executable text')
    symbols = {}
    for section in sections:
        if section[1] != 2: continue
        if section[9] != 24 or section[5] % 24 or section[6] >= count: raise ValueError('Symbol table bounds')
        names_data = contents(sections[section[6]])
        raw = contents(section)
        for at in range(0, len(raw), 24):
            name, info, other, index, value, size = struct.unpack_from('<IBBHQQ', raw, at)
            label = string(names_data, name)
            if label and index == 0: raise ValueError('Undefined symbol')
            if label and index == text_index:
                if value >= sections[text_index][5]: raise ValueError('Symbol outside text')
                symbols[label] = value
    return contents(sections[text_index]), symbols


def array(name, data):
    rows = [', '.join('0x%02x' % b for b in data[i:i+16]) for i in range(0, len(data), 16)]
    return 'STATIC CONST UINT8 ' + name + '[] = {\n  ' + ',\n  '.join(rows) + '\n};\n'


def build(kernel_path, output):
    kernel_path = Path(kernel_path)
    data = kernel_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != PIN: raise ValueError('Wrong pinned kernel')
    sys.path.insert(0, str(HERE.parent / 'xnu-preflight'))
    sys.path.insert(0, str(HERE.parent / 'xnu-handoff'))
    from payload import materialize
    from audit_abi import audit_entry
    entry = audit_entry(kernel_path)
    plan, mapped = materialize(data)
    if plan.Span != 0x1544000 or plan.EntryOffset != ENTRY_OFFSET or entry['branch_target_va'] - plan.VmBase != PATCH_OFFSET:
        raise ValueError('Kernel entry profile')
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    results = {}
    for label, symbol in [('checkpoint', 'kernel_checkpoint_begin'), ('transition', 'transition_begin')]:
        obj, elf = output / (label + '.o'), output / (label + '.elf')
        subprocess.run(['clang', '--target=aarch64-none-elf', '-march=armv9-a', '-c', str(HERE / (label + '.S')), '-o', str(obj)], check=True, capture_output=True)
        subprocess.run(['ld.lld', '--no-relax', '-Ttext=0', '-e', symbol, str(obj), '-o', str(elf)], check=True, capture_output=True)
        blob, symbols = extract_elf(elf.read_bytes())
        if symbols.get(symbol) != 0: raise ValueError('Blob entry must be zero')
        (output / (label + '.bin')).write_bytes(blob)
        dump = subprocess.run(['llvm-objdump', '-d', str(elf)], capture_output=True, text=True, check=True)
        (output / (label + '.disassembly.txt')).write_text(dump.stdout)
        results[label] = blob, symbols
    stub, stub_symbols = results['checkpoint']; transition, transition_symbols = results['transition']
    if len(stub) > 4096 - 0x5c: raise ValueError('Stub crosses owned executable page')
    matches = [s for s in plan.Segments[:plan.Count] if s.Offset <= PATCH_OFFSET and PATCH_OFFSET + len(stub) <= s.Offset + s.FileSize and s.Protection == 5]
    if len(matches) != 1: raise ValueError('Patch must fit one file-backed executable segment')
    original = mapped[PATCH_OFFSET:PATCH_OFFSET+len(stub)]
    changed = bytearray(mapped); changed[PATCH_OFFSET:PATCH_OFFSET+len(stub)] = stub
    if changed[ENTRY_OFFSET:ENTRY_OFFSET+4] != struct.pack('<I', 0x140006f5):
        raise ValueError('Original entry branch changed')
    sha = lambda b: hashlib.sha256(b).hexdigest()
    report = dict(kernel_sha256=PIN, original_entry_pa=BASE+ENTRY_OFFSET,
                  checkpoint_pa=BASE+PATCH_OFFSET, transition_pa=0x881604000,
                  original_entry_instruction=entry['instruction'], stub_bytes=len(stub),
                  transition_bytes=len(transition), stub_sha256=sha(stub),
                  transition_sha256=sha(transition), original_patch_sha256=sha(original),
                  instrumented_mapped_sha256=sha(changed), checkpoint_symbols=stub_symbols,
                  transition_symbols=transition_symbols, hardware_tested=False,
                  original_cpu_init_executed=False,
                  model_scope='Instruction/control-flow checks only; system-register and cache hooks are models')
    header = '// Generated from fixed input; do not edit.\n'
    for name, blob in [('mEntryStub', stub), ('mEntryTransition', transition),
                       ('mEntryOriginalPatch', original), ('mEntryStubHash', bytes.fromhex(sha(stub))),
                       ('mEntryTransitionHash', bytes.fromhex(sha(transition))),
                       ('mEntryMappedHash', bytes.fromhex(sha(changed)))]:
        header += array(name, blob)
    (output / 'EntryBlobs.h').write_text(header)
    (output / 'proof.json').write_text(json.dumps(report, indent=2) + '\n')
    return header, report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--kernel', required=True); p.add_argument('--out', required=True)
    a = p.parse_args(); _, report = build(a.kernel, a.out); print(json.dumps(report, indent=2))

