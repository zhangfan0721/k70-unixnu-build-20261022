#!/usr/bin/env python3
"""Compile the pinned Apple ABI and inspect the pinned kernel's entry branch."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile

from handoff import BASE, KERNEL

HEADER_BLOB = 'eab75014f92bb6475bdd4225b6e074ad82652ae5'
OFFSETS = dict(Revision=0, Version=2, virtBase=8, physBase=0x10, memSize=0x18,
               topOfKernelData=0x20, Video=0x28, machineType=0x58,
               deviceTreeP=0x60, deviceTreeLength=0x68, CommandLine=0x6c,
               bootFlags=0x470, memSizeActual=0x478)


def audit_header(path):
    raw = path.read_bytes().replace(b'\r\n', b'\n')
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if blob != HEADER_BLOB:
        raise ValueError('Apple boot.h is not the pinned Git blob')
    # Preserve the exact original declarations. Only unavailable project includes
    # are removed; these supply no additional struct fields in this header.
    header = re.sub(r'^#include[^\n]*$', '', raw.decode(), flags=re.MULTILINE)
    program = '#include <stdint.h>\n#include <stddef.h>\n#include <stdio.h>\n' + header
    program += '\n_Static_assert(sizeof(void*) == 8 && sizeof(unsigned long) == 8, "64-bit ABI host");\n'
    program += 'int main(void) {\nprintf("size %zu\\n", sizeof(boot_args));\n'
    for field in OFFSETS:
        program += f'printf("{field} %zu\\n", offsetof(boot_args, {field}));\n'
    program += 'return 0; }\n'
    with tempfile.TemporaryDirectory(prefix='k70-apple-abi-') as temp:
        source = Path(temp) / 'abi.c'; binary = Path(temp) / 'abi'
        source.write_text(program)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                        str(source), '-o', str(binary)], check=True, capture_output=True)
        result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    values = {key: int(value) for key, value in (line.split() for line in result.stdout.splitlines())}
    size = values.pop('size')
    if values != OFFSETS or size != 0x480:
        raise ValueError('Compiled original Apple ABI differs from the candidate ABI')
    return dict(size=size, offsets=values, header_git_blob=blob,
                source_commit='d8b80295118ef25ac3a784134bcf95cd8e88109f',
                original_struct_compiled=True, line_endings_normalized=True)


def audit_entry(path):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != KERNEL['kernel_sha256']:
        raise ValueError('Wrong kernel SHA-256')
    count, total = struct.unpack_from('<II', data, 16)
    end = 32 + total
    if end > len(data) or count > 128:
        raise ValueError('Invalid command table')
    offset, entry, symbol_table = 32, None, None
    segments = []
    for _ in range(count):
        if offset + 8 > end:
            raise ValueError('Truncated command')
        cmd, size = struct.unpack_from('<II', data, offset)
        if size < 8 or offset + size > end:
            raise ValueError('Invalid command extent')
        if cmd == 0x19:
            segments.append(struct.unpack_from('<4Q', data, offset + 24))
        elif cmd == 5:
            entry = struct.unpack_from('<Q', data, offset + 272)[0]
        elif cmd == 2:
            symbol_table = struct.unpack_from('<4I', data, offset + 8)
        offset += size
    if offset != end or entry != KERNEL['vm_base'] + KERNEL['entry_offset'] or symbol_table is None:
        raise ValueError('Pinned entry/symbol metadata mismatch')
    symoff, nsyms, stroff, strbytes = symbol_table
    if symoff + 16 * nsyms > len(data) or stroff + strbytes > len(data):
        raise ValueError('Invalid symbol/string extent')
    symbols = {}
    for i in range(nsyms):
        index, _, _, _, value = struct.unpack_from('<IBBHQ', data, symoff + i * 16)
        if index >= strbytes:
            raise ValueError('Bad symbol string offset')
        at = stroff + index; stop = data.find(b'\0', at, stroff + strbytes)
        if stop < 0:
            raise ValueError('Unterminated symbol')
        name = data[at:stop]
        if name in (b'__start', b'_start_first_cpu'):
            symbols[name] = value
    matches = [(fileoff + entry - vm) for vm, _, fileoff, filesize in segments
               if vm <= entry and entry + 4 <= vm + filesize]
    if len(matches) != 1 or matches[0] + 4 > len(data):
        raise ValueError('Entry is not uniquely file backed')
    instruction = struct.unpack_from('<I', data, matches[0])[0]
    if instruction & 0xfc000000 != 0x14000000:
        raise ValueError('Entry is not an unconditional ARM64 B instruction')
    immediate = instruction & 0x3ffffff
    if immediate & 0x2000000: immediate -= 1 << 26
    target = entry + immediate * 4
    if symbols.get(b'__start') != entry or symbols.get(b'_start_first_cpu') != target:
        raise ValueError('Entry branch does not reach the pinned first-CPU symbol')
    return dict(kernel_sha256=KERNEL['kernel_sha256'], entry_va=entry,
                branch_target_va=target, instruction=hex(instruction),
                physical_entry=BASE + KERNEL['entry_offset'], entry_symbol='__start',
                target_symbol='_start_first_cpu', x0_preserved_by_entry_branch=True,
                kernel_executed=False)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--header', type=Path, required=True)
    cli.add_argument('--kernel', type=Path, required=True)
    cli.add_argument('--out', type=Path, required=True)
    args = cli.parse_args()
    proof = dict(apple_abi=audit_header(args.header), binary_entry=audit_entry(args.kernel),
                 execution_ready=False)
    with args.out.open('x') as output:
        output.write(json.dumps(proof, indent=2) + '\n')
    print('Pinned original Apple ABI and actual kernel entry branch verified; no execution.')


if __name__ == '__main__':
    main()
