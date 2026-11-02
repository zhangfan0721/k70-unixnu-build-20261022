"""Darwin 22 integration only. All edits are confined to a generated build tree."""
import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
FORMAL = HERE.parent / 'formal-xnu'
sys.path.insert(0, str(FORMAL))
from prepare import observer_source, replace_once
from macho_asm import normalize_inline_asm

CORE = 'b6ae99c17194e6a18fd819d3148e69fe405e91fc'
DEVICE = 'd4dbb3683023a17bb468b9774f52c87f3060e739'
XNU = '1b191cb58250d0705d8a51287127505aa4bc0789'
BASE_PATCHES = (
    'local-availability', 'cxx-flag-dependencies', 'kernel-sdk-root',
    'non-apple-cache-monitor', 'native-4k-bootstrap-capacity',
    'non-apple-pmap-field', 'armvirt-platform-personality',
    'architectural-timer-entry', 'native-dt-panic-region',
    'native-quiet-managed-page-report', 'source-corecrypto14-bootstrap',
    'source-pthread-bootstrap', 'non-apple-iommu-bootstrap',
)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def apply(root, patch):
    subprocess.run(['git', '-C', str(root), 'apply', '--check', '-'],
                   input=patch, text=True, check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), 'apply', '-'], input=patch,
                   text=True, check=True, capture_output=True)


def edit(root, name, before, after):
    path = root / name
    path.write_text(replace_once(path.read_text(), before, after))


def diagnostic_hooks(root, font):
    # Same observer, framebuffer guard, physical entry helpers and online gate
    # as accepted candidate08. Only the Darwin22 call-site contexts differ.
    header = '''// SPDX-License-Identifier: MIT
#ifndef XNU_BOOT_PROGRESS_H
#define XNU_BOOT_PROGRESS_H
#include <stdint.h>
void boot_progress_init(void);
void boot_progress_start(void);
int boot_progress_active(void);
void boot_progress_bind(uintptr_t,unsigned,unsigned,unsigned,unsigned);
void boot_progress_putc(char);
void boot_progress_stage(const char *);
void boot_progress_irq(uint64_t,uint64_t,uint64_t);
void boot_progress_poll(void);
void boot_progress_user_breakpoint(void *,unsigned);
void boot_progress_user_abort(void *,unsigned,uint64_t);
void boot_progress_critical_exit(int,char *,unsigned long);
void boot_progress_process_stage(int,const char *,const char *);
void boot_progress_exit(int,const char *,int,unsigned,uint64_t);
#endif
'''
    additions = {
        'osfmk/kern/boot_progress.h': header,
        'pexpert/arm/k70_formal_diag.c': observer_source() + '\n' + normalize_inline_asm((FORMAL / 'KernelAdapter.c').read_text()),
        'pexpert/arm/Font.h': font.read_text(),
        'pexpert/arm/FramebufferGuard.h': (FORMAL / 'FramebufferGuard.h').read_text(),
        'pexpert/arm/BootstrapMap.h': (FORMAL / 'BootstrapMap.h').read_text(),
        'osfmk/arm64/k70_formal_entry.s': (FORMAL / 'EntryDiagnostics.s').read_text(),
    }
    for name, text in additions.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise ValueError('Unexpected existing diagnostic source: ' + name)
        path.write_text(text)
    edit(root, 'osfmk/kern/Makefile', '\tbacktrace.h \\\n', '\tbacktrace.h \\\n\tboot_progress.h \\\n')
    name = 'pexpert/arm/pe_serial.c'
    p = root / name
    p.write_text('#include "k70_formal_diag.c"\n' + p.read_text())
    files = ('osfmk/arm/arm_init.c', 'osfmk/kern/startup.c',
             'osfmk/console/video_console.c', 'osfmk/console/serial_console.c',
             'pexpert/arm/pe_kprintf.c', 'bsd/kern/bsd_init.c',
             'osfmk/arm64/sleh.c', 'bsd/kern/kern_exec.c')
    for name in files:
        p = root / name
        p.write_text('#include <kern/boot_progress.h>\n' + p.read_text())
    name = 'osfmk/arm/arm_init.c'
    edit(root, name, '\tarm_setup_pre_sign();',
         '\textern void k70_formal_c_entry(void *);\n\tk70_formal_c_entry(args);\n\tarm_setup_pre_sign();')
    edit(root, name, '\tPE_init_platform(FALSE, args); /* Get platform expert set up */',
         '\tPE_init_platform(FALSE, args); /* Get platform expert set up */\n\textern void k70_formal_early(void *);\n\tk70_formal_early(args);')
    edit(root, name, '\tarm_vm_init(xmaxmem, args);',
         '\tboot_progress_stage("arm_vm_init enter");\n\tarm_vm_init(xmaxmem, args);\n\textern void k70_formal_after_vm(void);\n\tk70_formal_after_vm();')
    name = 'osfmk/kern/startup.c'
    for f in ('kernel_bootstrap_log', 'kernel_bootstrap_thread_log'):
        edit(root, name, f + '(const char *message)\n{',
             f + '(const char *message)\n{\n\tboot_progress_stage(message);')
    edit(root, name, '\tclock_service_create();', '\tclock_service_create();\n\tboot_progress_start();')
    edit(root, name, '\tinitialize_screen(NULL, kPEAcquireScreen);',
         '\tinitialize_screen(NULL, kPEAcquireScreen);\n\textern void k70_formal_thread_start(void);\n\tk70_formal_thread_start();')
    for name, anchor in (
            ('osfmk/console/video_console.c', 'vcputc_options(char c, __unused bool poll)\n{'),
            ('osfmk/console/serial_console.c', '_cnputc(char c, bool poll)\n{')):
        edit(root, name, anchor, anchor + '\n\tif (boot_progress_active()) { boot_progress_putc(c); return; }')
    binding = '\tboot_progress_bind(vinfo.v_baseaddr, vinfo.v_width, vinfo.v_height, vinfo.v_rowbytes, vinfo.v_depth);\n'
    edit(root, 'osfmk/console/video_console.c', '\t\t// If we changed the virtual address, remove the old mapping',
         '\t' + binding + '\n\t\t// If we changed the virtual address, remove the old mapping')
    edit(root, 'osfmk/console/video_console.c', '\t}\n}\n\nvoid vcattach(void);',
         '\t}\n' + binding + '}\n\nvoid vcattach(void);')
    edit(root, 'pexpert/arm/pe_kprintf.c', 'PE_init_kprintf(void)\n{',
         'PE_init_kprintf(void)\n{\n\tif (boot_progress_active()) { PE_kputc = boot_progress_putc; return; }')
    name = 'bsd/kern/bsd_init.c'
    edit(root, name, 'bsd_init(void)\n{', 'bsd_init(void)\n{\n\tboot_progress_stage("bsd_init enter");')
    edit(root, name, '#define bsd_init_kprintf(x, ...)\n', '#define bsd_init_kprintf(x, ...) boot_progress_stage("bsd_init: " x)\n')
    edit(root, name, '\terr = IOFindBSDRoot(rootdevice, sizeof(rootdevice), &rootdev, &flags);',
         '\textern void k70_formal_cpu_summary(void);\n\tk70_formal_cpu_summary();\n\terr = IOFindBSDRoot(rootdevice, sizeof(rootdevice), &rootdev, &flags);')
    edit(root, name, '\t\tif (0 == (err = vfs_mountroot())) {',
         '\t\tboot_progress_stage("vfs_mountroot enter");\n\t\tif (0 == (err = vfs_mountroot())) {\n\t\t\tboot_progress_stage("vfs_mountroot mounted; authentication pending");')
    edit(root, 'bsd/kern/kern_exec.c', 'load_init_program(proc_t p)\n{',
         'load_init_program(proc_t p)\n{\n\tboot_progress_stage("load_init_program enter");')
    edit(root, 'osfmk/arm64/sleh.c', '\tsleh_interrupt_handler_prologue(state, DBG_INTR_TYPE_OTHER);',
         '\tsleh_interrupt_handler_prologue(state, DBG_INTR_TYPE_OTHER);\n\tboot_progress_irq(get_saved_state_pc(state), get_saved_state_cpsr(state), get_saved_state_sp(state));')
    # The accepted entry patch applies after the guarded Apple tunables and
    # bounded 4K bootstrap pool patches, except its first include context.
    patch = (FORMAL / 'EntryDiagnostics.patch').read_text()
    start = patch.index('@@ -237,')
    apply(root, '--- a/osfmk/arm64/start.s\n+++ b/osfmk/arm64/start.s\n' + patch[start:])
    edit(root, 'osfmk/arm64/start.s', '#include <mach_assert.h>', '#include <mach_assert.h>\n#include "k70_formal_entry.s"')
    apply(root, (FORMAL / 'CryptoBeforeIokit.patch').read_text())
    edit(root, 'bsd/kern/source_pthread_bootstrap.c', '519.120.4', '514.100.2')


def integration_patch(core, source, font, staging):
    if staging.exists():
        raise ValueError('Use a new patch staging directory')
    patches = [(name, (core / 'patches/xnu' / (name + '.patch')).read_text()) for name in BASE_PATCHES]
    # 22 has no SPTM pmap. Retain the existing 64-bit PA fix for its real pmap.
    pmap = (core / 'patches/xnu/zzx-pmap-sync-64bit-pa.patch').read_text().split('diff --git a/osfmk/arm64/sptm/')[0]
    patches.append(('pmap-64bit-pa', pmap))
    for p in sorted((HERE / 'patches').glob('*.patch')):
        patches.append((p.name, p.read_text()))
    names = set()
    for _, patch in patches:
        names.update(re.findall(r'^--- a/(.+)$', patch, re.M))
    names.update(('config/MASTER', 'config/MASTER.arm64.bcm2837', 'osfmk/conf/files.arm64',
                  'makedefs/MakeInc.kernel', 'osfmk/kern/Makefile', 'osfmk/arm64/start.s', 'pexpert/arm/pe_serial.c',
                  'osfmk/arm/arm_init.c', 'osfmk/kern/startup.c', 'osfmk/console/video_console.c',
                  'osfmk/console/serial_console.c', 'pexpert/arm/pe_kprintf.c', 'bsd/kern/bsd_init.c',
                  'osfmk/arm64/sleh.c', 'bsd/kern/kern_exec.c'))
    originals = {}
    for name in sorted(names):
        data = (source / name).read_text()
        originals[name] = data
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data)
    subprocess.run(['git', 'init', '-q', str(staging)], check=True)
    for name, patch in patches:
        try:
            apply(staging, patch)
        except subprocess.CalledProcessError as error:
            raise ValueError(name + ': ' + error.stderr) from error
    edit(staging, 'config/MASTER', 'options   NOS_ARM_ASM', 'options   CONFIG_APPLE_AMCC\t\t\t# <apple_amcc>\n\noptions   NOS_ARM_ASM')
    p = staging / 'config/MASTER.arm64.bcm2837'
    p.write_text(replace_once(p.read_text(), '[ arm64 config_pmap_ppl ', '[ arm64 config_pmap_ppl nos_arm_asm nos_arm_pmap ').replace(' sched_hygiene_debug', ''))
    p = staging / 'osfmk/conf/files.arm64'
    p.write_text(''.join(line.rstrip('\n') + (' apple_amcc' if re.match(r'osfmk/arm64/amcc_rorgn_.* optional ', line) else '') + '\n' for line in p.read_text().splitlines(True)))
    edit(staging, 'makedefs/MakeInc.kernel', '$(TARGET)/$(KERNEL_FILE_NAME).unstripped: $(addprefix',
         '$(TARGET)/$(KERNEL_FILE_NAME).unstripped: $(XNU_EXTERNAL_KERNEL_ARCHIVES)\n\n$(TARGET)/$(KERNEL_FILE_NAME).unstripped: $(addprefix')
    name = 'osfmk/arm64/start.s'
    edit(staging, name, '#include <arm64/tunables/tunables.s>', '#if defined(APPLE_ARM64_ARCH_FAMILY)\n#include <arm64/tunables/tunables.s>\n#endif')
    edit(staging, name, '\tmrs x12, MIDR_EL1\n\n\tAPPLY_TUNABLES x12, x13, x14',
         '#if defined(APPLE_ARM64_ARCH_FAMILY)\n\tmrs x12, MIDR_EL1\n\n\tAPPLY_TUNABLES x12, x13, x14\n#endif')
    diagnostic_hooks(staging, font)
    result = ''
    hashes = {}
    for path in sorted(staging.rglob('*')):
        if not path.is_file() or '.git' in path.parts:
            continue
        name = path.relative_to(staging).as_posix()
        before, after = originals.get(name, ''), path.read_text()
        if before == after:
            continue
        result += ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
            fromfile='a/' + name if name in originals else '/dev/null', tofile='b/' + name))
        hashes[name] = {'before': hashlib.sha256(before.encode()).hexdigest() if name in originals else None,
                        'after': hashlib.sha256(after.encode()).hexdigest()}
    return result, {'xnu_commit': XNU, 'selected_patches': [n for n, _ in patches], 'files': hashes,
                    'patch_sha256': hashlib.sha256(result.encode()).hexdigest(),
                    'hardware_tested': False, 'original_component_abi_verified': False}


def retarget_scripts(core, device, tree):
    # Build copies only: no mutation of any pinned repository or baseline08.
    names = ('build-xnu-4k-baseline.sh', 'build-corecrypto-14.py', 'build-libpthread-kernel.py', 'build-firehose.sh')
    for name in names:
        p = tree / 'scripts' / name
        text = p.read_text()
        text = text.replace('ios17.0', 'ios16.0').replace('min=17.0', 'min=16.0').replace('TARGET=17.0', 'TARGET=16.0')
        text = text.replace(',17.0', ',16.0')
        text = text.replace('0x110000', '0x100000').replace('iOS 17', 'iOS 16').replace('ios17', 'ios16')
        if name == 'build-libpthread-kernel.py':
            text = text.replace('c0e60fb5ecfc54cf379c261d3f9572cc22ded891', 'a6c70ca0e544347a0377babf748f831577ec24f9').replace('pthread519_', 'pthread514_').replace('Darwin 23', 'Darwin 22')
        if name == 'build-xnu-4k-baseline.sh':
            text = replace_once(text, ' "$ROOT"/kits/NativePrelink/patches/*.patch', '')
            text = text.replace('.unstripped.noctf', '.unstripped')
        p.write_text(text)
    shutil.copy2(FORMAL / 'macho_asm.py', tree / 'scripts/k70_macho_asm.py')
    # Original device recipe is read through git, independent of local edits.
    original = subprocess.check_output(['git', '-C', str(device), 'show', DEVICE + ':scripts/build-arm-driver.py'], text=True)
    if hashlib.sha256(original.encode()).hexdigest() != '7d520749568581c3cf741e732f53d0553f66344b5cda3a473c3d12822a344d40':
        raise ValueError('Unexpected original CPU archive builder')
    anchor = 'source = ROOT / "drivers" / component / (component + ".cpp")'
    original = replace_once(original, anchor, anchor + '\nif component == "ArmCpu":\n    from k70_macho_asm import prepare_armcpu_source\n    source = prepare_armcpu_source(source, ROOT / ".cache/k70-armcpu")')
    (tree / 'scripts/build-arm-driver.py').write_text(original.replace('0x110000', '0x100000').replace('iOS 17', 'iOS 16'))


def prepare(core, device, tree, font):
    patch, report = integration_patch(core, tree / 'refer/xnu', font, tree / '.cache/iphone16-patch-source')
    local = tree / '.cache/iphone16-patches'
    local.mkdir()
    (local / '000-iphone16-integration.patch').write_text(patch)
    link = tree / 'patches/xnu'
    if not link.is_symlink():
        raise ValueError('Expected generated xnu patch link')
    link.unlink()
    link.symlink_to(local.resolve())
    retarget_scripts(core, device, tree)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--core', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--font', type=Path, required=True)
    p.add_argument('--staging', type=Path, required=True)
    args = p.parse_args()
    patch, report = integration_patch(args.core, args.source, args.font, args.staging)
    args.staging.with_suffix('.patch').write_text(patch)
    args.staging.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
