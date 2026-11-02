"""Bounded real-generator/compile probe; never emits a bootable candidate."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path.cwd()
EVIDENCE = ROOT / 'iig-evidence'
EVIDENCE.mkdir()
INTEGRATION = ROOT / 'integration'
# Remove the newer-layout backport in an isolated adapter copy only.
adapter_dir = INTEGRATION / 'iphone16-probe'
shutil.copytree(INTEGRATION / 'iphone16', adapter_dir)
(adapter_dir / 'patches/003-iig.patch').unlink()
sys.path.insert(0, str(adapter_dir))
gate = importlib.import_module('build')
core, device = ROOT / 'upstream', ROOT / 'device'
font = ROOT / 'uefi/Silicon/Silicium/SiliciumPkg/Library/FrameBufferSerialPortLib/Font.h'
gate.check(core, device, font)
for option in ('--help', '--version'):
    p = subprocess.run(['xcrun', '--sdk', 'iphoneos', 'iig', option], capture_output=True, text=True)
    (EVIDENCE / ('iig-' + option[2:] + '.txt')).write_text(p.stdout + p.stderr)
sys.path.insert(0, str(core / 'scripts'))
cli, config, kernel = (importlib.import_module('unixnu.' + n) for n in ('cli', 'config', 'kernel'))
options = cli.parser().parse_args(['build', 'kernel', '-D', str(adapter_dir / 'device'),
                                  '--out', str(ROOT / 'out-probe'), '-j', '4'])
ctx = config.Context(options)
ctx.work.mkdir(parents=True, exist_ok=True)
shutil.copy2(adapter_dir / 'device/configs/vermeer16_defconfig', ctx.config_path)
ctx.config = config.parse_config(ctx.config_path.read_text())
modules = cli.prepare(ctx, ['kernel'])
gate.adapter.prepare(core, device, ctx.tree, font)
env = dict(os.environ)
env.update(kernel.xnu_env(ctx))
env.update(kernel.version_env(modules))
env.update(XNU_BUILD_TARGET='installhdrs', XNU_BOOTSTRAP='1', XNU_BOOT_PROGRESS='0', JOBS='4')
# The script's trailing kernel sealer will reject a headers-only build. This
# probe requires the real generated headers/code, then independently compiles.
with (EVIDENCE / 'headers.log').open('w') as stream:
    result = subprocess.run(['bash', str(ctx.tree / 'scripts/build-xnu-4k-baseline.sh')],
                            cwd=ctx.tree, env=env, stdout=stream, stderr=subprocess.STDOUT)
generated = list((ctx.tree / 'build/xnu').rglob('IOService.iig.cpp'))
if not generated:
    raise ValueError('No real IOService IIG output; inspect headers.log')
source = next((p for p in generated if '/ios-obj/' in str(p)), generated[0])
body = source.read_text()
shutil.copy2(source, EVIDENCE / 'IOService.iig.cpp')
if 'kernelContent' in body or 'IORPCMessageFromMach' not in body:
    raise ValueError('Generated code does not preserve legacy message decoding')
header = ctx.tree / '.cache/xnu-work/iokit/IOKit/IORPC.h'
shutil.copy2(header, EVIDENCE / 'IORPC.h')
if 'kernelContent' in header.read_text():
    raise ValueError('Newer IORPC header leaked into probe')
with zipfile.ZipFile(ROOT / 'reference.zip') as z:
    names = [n for n in z.namelist() if n.endswith('/IOPlatformExpert.cpo.json')]
    if len(names) != 1:
        raise ValueError('Expected one real reference compile record')
    raw = z.read(names[0])
record = json.loads(raw.decode().strip().rstrip(','))
(EVIDENCE / 'reference-compile-record.json').write_bytes(raw)
old_tree = record['directory'].split('/build/xnu/ios-obj/')[0]
directory = Path(record['directory'].replace(old_tree, str(ctx.tree)))
directory.mkdir(parents=True, exist_ok=True)
compiler = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--find', 'clang++'], text=True).strip()
command, removed = [compiler], []
arguments = record['arguments']
index = 1
while index < len(arguments):
    value = arguments[index]
    if value == '-Xclang':
        # These compiler16 frontend toggles are not the IIG or kernel ABI.
        removed.extend(arguments[index:index + 2])
        index += 2
        continue
    if value == record['file']:
        command.append(str(source))
    elif value == '-o':
        command.extend(['-o', str(EVIDENCE / 'IOService.iig.o')])
        index += 1
    else:
        command.append(value.replace(old_tree, str(ctx.tree)))
    index += 1
command += ['-Wno-unknown-warning-option']
(EVIDENCE / 'generated-compile-command.json').write_text(json.dumps(command, indent=2) + '\n')
with (EVIDENCE / 'generated-compile.log').open('w') as stream:
    subprocess.run(command, cwd=directory, stdout=stream, stderr=subprocess.STDOUT, check=True)
fixture = EVIDENCE / 'layout.cpp'
fixture.write_text('#include <IOKit/IORPC.h>\nstatic_assert(sizeof(IORPC) == 24);\n'
                   'static_assert(__builtin_offsetof(IORPC, sendSize) == 16);\n'
                   'static_assert(__builtin_offsetof(IORPC, replySize) == 20);\n')
layout = [str(fixture) if x == str(source) else str(EVIDENCE / 'layout.o') if x == str(EVIDENCE / 'IOService.iig.o') else x for x in command]
with (EVIDENCE / 'layout-compile.log').open('w') as stream:
    subprocess.run(layout, cwd=directory, stdout=stream, stderr=subprocess.STDOUT, check=True)
with (EVIDENCE / 'generated-disassembly.txt').open('w') as stream:
    subprocess.run(['xcrun', 'otool', '-tvV', str(EVIDENCE / 'IOService.iig.o')], stdout=stream, check=True)
(EVIDENCE / 'result.json').write_text(json.dumps({
    'real_generated_ioservice_compiled': True, 'legacy_message_decoding': True,
    'iorpc_bytes_asserted': 24, 'reference_record_sha256': hashlib.sha256(raw).hexdigest(),
    'generated_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'removed_compiler16_frontend_options': removed, 'headers_only_script_exit': result.returncode,
    'full_kernel_built': False, 'original_components_runtime_tested': False}, indent=2) + '\n')
