"""Compile with real XNU rules and exercise the real driver record consumer.

Local interface fixtures never become production build records or archives.
The actual driver compile is expected to stop at missing macOS kernel headers;
its command proves consumption, not driver ABI or a complete archive build.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


def check(rule, device, core, out):
    out.mkdir()
    text = rule.read_text()
    definitions = '\n'.join(re.findall(r'^[CPS]_RULE_1[AB]=.*$', text, re.M))
    targets = ('startup.o', 'IOPlatformExpert.cpo', 'entry.o')
    (out / 'startup.c').write_text('unsigned record_c(unsigned x) { return x * 3 + 1; }\n')
    (out / 'IOPlatformExpert.cpp').write_text('extern "C" unsigned record_cpp(unsigned x) { return x * 5 + 1; }\n')
    (out / 'entry.s').write_text('.text\n.globl _record_asm\n_record_asm:\n add x0, x0, #7\n ret\n')
    (out / 'Makefile').write_text('''KCC=clang --target=arm64-apple-ios16.0
KC++ = clang++ --target=arm64-apple-ios16.0
S_KCC=clang --target=arm64-apple-ios16.0
CFLAGS=-ffreestanding
''' + definitions + '''
all: startup.o IOPlatformExpert.cpo entry.o
startup.o: startup.c
	$(C_RULE_1A) $(C_RULE_1B) -o $@
IOPlatformExpert.cpo: IOPlatformExpert.cpp
	$(P_RULE_1A) $(P_RULE_1B)
entry.o: entry.s
	$(S_RULE_1A) $(S_RULE_1B) -o $@
''')
    subprocess.run(['make', '-j3'], cwd=out, check=True)
    records = {}
    for name in targets:
        path = out / (name + '.json')
        if not path.is_file():
            raise ValueError('Real compiler did not emit ' + path.name)
        record = json.loads(path.read_text().strip().rstrip(','))
        if Path(record['directory']).resolve() != out.resolve():
            raise ValueError('Unexpected compiler working directory')
        # Darwin assembly may record its preprocessing temporary .s output.
        if (name != 'entry.o' and record['output'] != name) or record['file'] not in record['arguments']:
            raise ValueError('Invalid real compile record')
        if not (out / name).is_file():
            raise ValueError('Record produced without its compiled object')
        records[name] = record
    # Invoke the pinned driver builder unchanged. It consumes the compiler's
    # actual C++ record and attempts the real ArmDTPlatform source, not a stub.
    tree = out / 'consumer'
    scripts = tree / 'scripts'
    scripts.mkdir(parents=True)
    revision = 'd4dbb3683023a17bb468b9774f52c87f3060e739'
    for name in ('scripts/build-arm-driver.py', 'drivers/ArmDTPlatform/ArmDTPlatform.cpp'):
        if name.startswith('scripts/'):
            data = subprocess.check_output(['git', '-C', str(device), 'show', revision + ':' + name])
        else:
            data = (core / name).read_bytes()
        path = tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    recipe = tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
    recipe.parent.mkdir(parents=True)
    recipe.write_bytes((out / 'IOPlatformExpert.cpo.json').read_bytes())
    result = subprocess.run([sys.executable, str(scripts / 'build-arm-driver.py'), 'ArmDTPlatform'],
                            capture_output=True, text=True)
    command = json.loads((tree / 'build/armdt-platform/compile-command.json').read_text())
    driver = str(tree / 'drivers/ArmDTPlatform/ArmDTPlatform.cpp')
    log = (tree / 'build/armdt-platform/compile.log').read_text()
    if driver not in command or not result.returncode or 'file not found' not in log:
        raise ValueError('Expected actual driver compilation to stop at missing local kernel headers')
    report = {'real_xnu_rules': str(rule), 'real_clang_records': list(records),
              'real_driver_builder_consumed_record_and_invoked_compiler': True,
              'full_driver_archive_built': False, 'local_limit': 'macOS kernel headers unavailable'}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('rule', 'device', 'core', 'out'):
        p.add_argument('--' + name, type=Path, required=True)
    args = p.parse_args()
    check(args.rule, args.device, args.core, args.out)
