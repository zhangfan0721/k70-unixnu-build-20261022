"""Check fixed-source patch application and actual iOS16 Mach-O instructions."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('iphone16_prepare', HERE / 'prepare.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def deployment(path):
    data = path.read_bytes()
    if struct.unpack_from('<4I', data) != (0xfeedfacf, 0x100000c, 0, 1):
        raise ValueError('Expected ARM64 Mach-O object')
    offset = 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, size = struct.unpack_from('<II', data, offset)
        if cmd == 0x32:
            if struct.unpack_from('<II', data, offset + 8) != (2, 0x100000):
                raise ValueError('Expected iOS16 target')
            return
        offset += size
    raise ValueError('No build version')


def main():
    p = argparse.ArgumentParser()
    for name in ('core', 'source', 'source-device', 'font', 'out'):
        p.add_argument('--' + name, type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir()
    patch, report = adapter.integration_patch(args.core, args.source, args.font, args.out / 'patched')
    (args.out / 'integration.patch').write_text(patch)
    (args.out / 'patch-report.json').write_text(json.dumps(report, indent=2) + '\n')
    scripts = args.out / 'tree/scripts'
    scripts.mkdir(parents=True)
    for name in ('build-xnu-4k-baseline.sh', 'build-corecrypto-14.py', 'build-libpthread-kernel.py', 'build-firehose.sh'):
        shutil.copy2(args.core / 'scripts' / name, scripts / name)
    adapter.retarget_scripts(args.core, args.source_device, scripts.parent)
    for path in scripts.glob('*.sh'):
        subprocess.run(['bash', '-n', str(path)], check=True)
    for path in scripts.iterdir():
        text = path.read_text()
        if any(v in text for v in ('ios17.0', 'min=17.0', 'TARGET=17.0', ',17.0', '0x110000', '.unstripped.noctf')):
            raise ValueError('Unretargeted deployment: ' + path.name)
    obj = args.out / 'observer.o'
    src = args.out / 'observer.c'
    src.write_text(adapter.observer_source())
    subprocess.run(['clang', '--target=arm64-apple-ios16.0', '-std=c11', '-ffreestanding',
        '-fno-builtin', '-O0', '-Wall', '-Wextra', '-Werror', '-I', str(args.out / 'patched/osfmk'),
        '-I', str(args.out / 'patched/pexpert/arm'), '-c', str(src), '-o', str(obj)], check=True)
    deployment(obj)
    disassembly = subprocess.check_output(['llvm-objdump', '-d', str(obj)], text=True).lower()
    for pattern in (r'at\s+s1e1w', r'at\s+s1e1r', r'mrs\s+x\d+, par_el1', r'msr\s+par_el1, x\d+', r'msr\s+daif, x\d+'):
        if not re.search(pattern, disassembly):
            raise ValueError('Lost observer instruction: ' + pattern)
    src = args.out / 'entry.S'
    src.write_text('''#define EXT(x) _##x
#define LEXT(x) _##x:
#include "k70_formal_entry.s"
.text
.globl _iphone16_entry_check
_iphone16_entry_check:
 K70_PREPARE_DISPLAY
 K70_MARK x20, 0x00ff00ff, 0
 K70_MARK x20, 0x00ffffff, 1
 K70_MARK x20, 0x00ffff00, 2
 ret
K70_ENTRY_HELPERS
''')
    obj = args.out / 'entry.o'
    subprocess.run(['clang', '--target=arm64-apple-ios16.0', '-x', 'assembler-with-cpp',
        '-I', str(args.out / 'patched/osfmk/arm64'), '-c', str(src), '-o', str(obj)], check=True)
    deployment(obj)
    (args.out / 'entry-disassembly.txt').write_text(subprocess.check_output(['llvm-objdump', '-d', str(obj)], text=True))
    report = {'fixed_xnu_commit': adapter.XNU, 'patch_sha256': report['patch_sha256'],
        'arm64_ios16_observer_and_entry_assembled': True, 'observer_translation_and_daif_instructions_retained': True,
        'generated_recipe_syntax_checked': True, 'full_kernel_compiled': False,
        'hardware_tested': False, 'original_component_abi_verified': False}
    (args.out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
