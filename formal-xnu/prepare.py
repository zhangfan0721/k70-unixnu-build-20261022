"""Pinned source-only diagnostics and formal firmware; never runs device tools."""
import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from macho_asm import normalize_inline_asm

HERE = Path(__file__).resolve().parent
FORMAL_MODULES = (
    'UniXNUPkg/Application/UniXNU/UniXNU.inf',
    'UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf',
    'UniXNUPkg/Driver/UniXNURamDiskDxe/UniXNURamDiskDxe.inf',
    'DarwinBootPkg/Driver/DarwinBoot.inf',
    'MdeModulePkg/Universal/Disk/DiskIoDxe/DiskIoDxe.inf',
    'MdeModulePkg/Universal/Disk/PartitionDxe/PartitionDxe.inf',
    'FatPkg/EnhancedFatDxe/Fat.inf',
    'MdeModulePkg/Universal/Disk/UnicodeCollation/EnglishDxe/EnglishDxe.inf',
)


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Unexpected pinned source anchor: '+before[:100])
    return text.replace(before, after, 1)


def observer_source():
    text = (HERE/'upstream/BootProgressMin.c').read_text()
    if hashlib.sha256(text.encode()).hexdigest() != '7daf44ba19a5c7592a161cd4d20c2287417cef19b21f553540369728a3f60b1d':
        raise ValueError('Unreviewed upstream observer source')
    text = replace_once(text, '#include "Font.h"', '#include "FramebufferGuard.h"\n#include "Font.h"')
    text = replace_once(text,
        '__asm__ volatile ("at s1e1r, %1; isb; mrs %0, par_el1" : "=r" (par) : "r" (address) : "memory");',
        '''uint64_t mask, saved;
    __asm__ volatile ("mrs %0, daif; msr daifset, #15; mrs %1, par_el1; "
        "at s1e1r, %3; isb; mrs %2, par_el1; msr par_el1, %1; msr daif, %0"
        : "=&r"(mask), "=&r"(saved), "=&r"(par) : "r"(address) : "memory");''')
    start = text.index('/* arm_vm_init() installs the physical aperture;')
    end = text.index('static const uint64_t bp_font', start)
    text = text[:start] + text[end:]
    start = text.index('\tif (!bp_translated(framebuffer)) {')
    end = text.index('\t/* Pick the largest legible cell', start)
    text = text[:start] + '''\tif (!k70_framebuffer_valid(framebuffer, 0xb8000000, width, height,
\t    rowbytes, depth, bp_write_probe, 0)) { return; }
''' + text[end:]
    text = replace_once(text, '\tuintptr_t framebuffer = base;',
                        '\tg_screen.bound = 0;\n\tuintptr_t framebuffer = base;')
    probe = '''static int bp_write_probe(uint64_t va, uint64_t *pa, void *context)
{
    (void)context;
#if defined(__aarch64__)
    uint64_t par, mask, saved;
    __asm__ volatile ("mrs %0, daif; msr daifset, #15; mrs %1, par_el1; "
        "at s1e1w, %3; isb; mrs %2, par_el1; msr par_el1, %1; msr daif, %0"
        : "=&r"(mask), "=&r"(saved), "=&r"(par) : "r"(va) : "memory");
    *pa = (par & UINT64_C(0x000ffffffffff000)) | (va & 4095);
    return !(par & 1);
#else
    *pa = va;
    return 0; /* Host execution cannot attest ARM translations. */
#endif
}

'''
    text = replace_once(text, 'static const uint64_t bp_font', probe+'static const uint64_t bp_font')
    text = replace_once(text, '\tbp_build();\n\tbp_flush();', '''\tif (!k70_framebuffer_valid((uintptr_t)g_screen.fb, 0xb8000000,
\t    g_screen.width, g_screen.height, g_screen.stride, 32, bp_write_probe, 0)) {
\t\tg_screen.bound = 0;
\t\treturn;
\t}
\tbp_build();
\tbp_flush();''')
    text = text.replace(' XNU BOOT PROGRESS  min-1 ', ' K70 FORMAL XNU  diagnostic-3 ')
    text = replace_once(text, 'static const uint64_t bp_font',
                        'volatile uint32_t k70_formal_milestones;\nstatic const uint64_t bp_font')
    text = replace_once(text, '\tbp_out_puts(&out, " IRQ=");',
        '\tbp_out_puts(&out, " VM=");\n\tbp_out_dec(&out, k70_formal_milestones);\n\tbp_out_puts(&out, " IRQ=");')
    text = text.replace('" STARTED" : " EARLY"','" CLOCK_CREATED" : " EARLY"')
    text = text.replace('LAST: clock service created; scheduler running', 'LAST: clock service created; thread not yet verified')
    start = text.index('\tg_state.irqs++;')
    end = text.index('\n}\n', start)
    text = text[:start] + '\t__atomic_add_fetch(&g_state.irqs, 1, __ATOMIC_RELAXED);\n\t/* IRQ path only records; rendering is deferred. */' + text[end:]
    # Strings from non-image kernel objects may cross a page boundary.
    text = text.replace('index < limit && source[index] != 0',
                        'index < limit && bp_readable(source + index) && source[index] != 0')
    text = text.replace('index < limit && prefix[index] != 0',
                        'index < limit && bp_readable(prefix + index) && prefix[index] != 0')
    text = text.replace('index < BP_MAX_COLS && source[index] != 0',
        'index < BP_MAX_COLS && bp_translated((uintptr_t)(source + index)) && source[index] != 0')
    text = text.replace('text != NULL && *text != 0 && out->used < BP_MAX_COLS',
        'text != NULL && out->used < BP_MAX_COLS && bp_translated((uintptr_t)text) && *text != 0')
    text = replace_once(text, 'state == NULL || !bp_readable(state)',
                        'state == NULL || !bp_readable(state) || !bp_readable((const char *)state + 7)')
    text = replace_once(text, '\treturn *(const volatile uint64_t *)',
        '\tif (!bp_readable((const char *)state + 271)) { return 0; }\n\treturn *(const volatile uint64_t *)')
    # Avoid a full mapping scan and repaint per console character.
    text = replace_once(text, '\tbp_character(character);\n\tbp_refresh();', '\tbp_character(character);')
    text = replace_once(text, '\tg_screen.painted = 1;',
        '#if defined(__aarch64__)\n\t__asm__ volatile ("dsb sy" ::: "memory");\n#endif\n\tg_screen.painted = 1;')
    # A fault/console re-entry never spins behind an interrupted renderer. IRQs
    # update only their own atomic counter. Other concurrent updates may be dropped.
    signatures = {
        'init': ('void', ''), 'start': ('void', ''), 'poll': ('void', ''),
        'bind': ('uintptr_t base, unsigned width, unsigned height, unsigned stride, unsigned depth', 'base,width,height,stride,depth'),
        'putc': ('char c', 'c'), 'stage': ('const char *s', 's'),
        'user_breakpoint': ('void *state, unsigned esr', 'state,esr'),
        'user_abort': ('void *state, unsigned esr, uint64_t far', 'state,esr,far'),
        'process_stage': ('int pid, const char *name, const char *stage', 'pid,name,stage'),
        'critical_exit': ('int pid, char *prefix, unsigned long length', 'pid,prefix,length'),
        'exit': ('int pid, const char *name, int rv, unsigned ns, uint64_t code', 'pid,name,rv,ns,code'),
    }
    wrappers = '\nstatic unsigned char k70_observer_busy;\n'
    for name, (params, args) in signatures.items():
        text = replace_once(text, '\nboot_progress_'+name+'(', '\nbp_impl_'+name+'(')
        wrappers += f'''void boot_progress_{name}({params}) {{
    if (__atomic_test_and_set(&k70_observer_busy, __ATOMIC_ACQUIRE)) {{ return; }}
    bp_impl_{name}({args});
    __atomic_clear(&k70_observer_busy, __ATOMIC_RELEASE);
}}
'''
    text = text.replace('void\nbp_impl_', 'static void\nbp_impl_')
    text = text.replace('bp_out_dec(&out, g_state.irqs);',
        'bp_out_dec(&out, __atomic_load_n(&g_state.irqs, __ATOMIC_RELAXED));')
    return normalize_inline_asm('#include <kern/boot_progress.h>\n' + text + wrappers)


def added_file(path, text):
    lines = text.rstrip('\n').splitlines()
    return f'--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n' + ''.join('+'+line+'\n' for line in lines)


def kernel_patch(font):
    patch = '''--- a/osfmk/kern/boot_progress.h
+++ b/osfmk/kern/boot_progress.h
@@ -3,4 +3,4 @@
 #define XNU_BOOT_PROGRESS_H
 #include <stdint.h>
-#if defined(XNU_BOOT_PROGRESS) && XNU_BOOT_PROGRESS
+#if 1 /* Standalone K70 backend; full UFS/root-dependent monitor remains disabled. */
 void boot_progress_init(void);
--- a/pexpert/arm/pe_serial.c
+++ b/pexpert/arm/pe_serial.c
@@ -15,2 +15,3 @@
  */
+#include "k70_formal_diag.c"
 #include <kern/clock.h>
--- a/osfmk/arm/arm_init.c
+++ b/osfmk/arm/arm_init.c
@@ -346,2 +346,4 @@
+\textern void k70_formal_c_entry(void *);
+\tk70_formal_c_entry(args);
 \tarm_setup_pre_sign();
\x20
@@ -371,2 +371,4 @@
 \tPE_init_platform(FALSE, args); /* Get platform expert set up */
+\textern void k70_formal_early(void *);
+\tk70_formal_early(args);
 \tboot_progress_init();
@@ -534,2 +536,4 @@
 \tarm_vm_init(xmaxmem, args);
+\textern void k70_formal_after_vm(void);
+\tk70_formal_after_vm();
 \tboot_progress_stage("arm_vm_init returned");
--- a/osfmk/kern/startup.c
+++ b/osfmk/kern/startup.c
@@ -716,5 +716,7 @@
 \tinitialize_screen(NULL, kPEAcquireScreen);
\x20
+\textern void k70_formal_thread_start(void);
+\tk70_formal_thread_start();
 \t/*
 \t *\tInitialize the shared region module.
 \t */
'''
    patch += '''--- a/bsd/kern/bsd_init.c
+++ b/bsd/kern/bsd_init.c
@@ -1132,1 +1132,3 @@
+\textern void k70_formal_cpu_summary(void);
+\tk70_formal_cpu_summary();
 \terr = IOFindBSDRoot(rootdevice, sizeof(rootdevice), &rootdev, &flags);
'''
    patch += (HERE/'EntryDiagnostics.patch').read_text()
    patch += (HERE/'CryptoBeforeIokit.patch').read_text()
    source = observer_source() + '\n' + normalize_inline_asm((HERE/'KernelAdapter.c').read_text())
    for path, text in [('pexpert/arm/k70_formal_diag.c', source),
                       ('pexpert/arm/FramebufferGuard.h', (HERE/'FramebufferGuard.h').read_text()),
                       ('pexpert/arm/Font.h', font),
                       ('pexpert/arm/BootstrapMap.h', (HERE/'BootstrapMap.h').read_text()),
                       ('osfmk/arm64/k70_formal_entry.s', (HERE/'EntryDiagnostics.s').read_text())]:
        patch += added_file(path, text)
    return patch


def firmware(root, dtb):
    # Reuse the tested conservative memory map and disabled auto-expansion policy.
    spec = importlib.util.spec_from_file_location('probe_prepare', HERE.parent/'uefi-probe/prepare.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    report = probe.generate(root, dtb)
    source = root/'Platforms/Xiaomi/vermeerProbePkg'
    target = root/'Platforms/Xiaomi/vermeerFormalPkg'
    if target.exists():
        raise ValueError('Refusing to overwrite formal firmware package')
    source.rename(target)
    for path in target.rglob('*'):
        if path.suffix not in ('.dsc','.fdf','.inc','.py','.inf','.c'):
            continue
        text = path.read_text().replace('vermeerProbePkg','vermeerFormalPkg').replace('vermeerProbe','vermeerFormal')
        text = '\n'.join(line for line in text.splitlines() if 'VermeerProbe.inf' not in line)+'\n'
        if path.name == 'vermeerProbe.dsc':
            text += '\n[LibraryClasses]\n  UniXNULib|UniXNUPkg/Library/UniXNULib/UniXNULib.inf\n'
            text += '\n[Components]\n'+''.join('  '+module+'\n' for module in FORMAL_MODULES)
        if path.name == 'vermeerProbe.fdf':
            text = replace_once(text, '  !include Include/DXE.inc',
                '  !include Include/DXE.inc\n'+''.join('  INF '+module+'\n' for module in FORMAL_MODULES))
        if path.name == 'DeviceBuild.py':
            # The probe intentionally removed this package search path.
            text = replace_once(text, '    PackagesPath = (',
                '    PackagesPath = (\n        os.path.join(os.environ["UNIXNU_ROOT"], "package"),\n'
                '        os.path.join(os.environ["UNIXNU_ROOT"], "drivers", "DarwinBoot"),')
        if path.name == 'ProbeBootOptions.c':
            text = text.replace('0x4E746B99, 0x462F, 0x4C10, {0x8A,0x77,0xC3,0xF8,0x3E,0x5D,0x4F,0x72}',
                '0x9B665204, 0xA133, 0x47A2, {0x93,0x96,0x9E,0x2B,0x37,0x0A,0x4E,0x25}')
            text = text.replace('Vermeer hardware probe', 'K70 formal UniXNU')
        path.write_text(text)
    (target/'vermeerProbe.dsc').rename(target/'vermeerFormal.dsc')
    (target/'vermeerProbe.fdf').rename(target/'vermeerFormal.fdf')
    shutil.copy2(root/'Resources/Configs/vermeerProbe.toml', root/'Resources/Configs/vermeerFormal.toml')
    shutil.copy2(root/'Resources/DTBs/vermeerProbe.dtb', root/'Resources/DTBs/vermeerFormal.dtb')
    report.update(package='vermeerFormalPkg', os_loader=True, payload_filesystem=True,
                  storage_modules='read-only initrd with FAT; no physical storage drivers',
                  partition_io=False, hardware_tested=False)
    return report


def shared_ramdisk(core):
    source = HERE/'upstream/UniXNURamDiskDxe'
    metadata = json.loads((HERE/'upstream/SOURCES.json').read_text())['UniXNURamDiskDxe']
    destination = core/'package/UniXNUPkg/Driver/UniXNURamDiskDxe'
    if destination.exists():
        raise ValueError('Refusing to overwrite ramdisk driver')
    for name, expected in metadata['files'].items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest() != expected:
            raise ValueError('Upstream ramdisk driver hash mismatch: '+name)
    shutil.copytree(source,destination)
    # Keep the pinned handoff contract, with explicit MMU-off maintenance
    # and a visible marker for each handoff boundary.
    loader=core/'drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c'
    original=loader.read_text()
    updated=replace_once(original,'means the kernel entry code ran.',
                         'means loader handoff reached; cyan=cache clean, blue=MMU off. XNU entry is magenta.')
    loader.write_text(updated)
    metadata['loader_diagnostic_change']={
        'before_sha256':hashlib.sha256(original.encode()).hexdigest(),
        'after_sha256':hashlib.sha256(updated.encode()).hexdigest()}
    entry=loader.with_name('Entry.S')
    before=hashlib.sha256(entry.read_bytes()).hexdigest()
    if before != '72d63bede2d0eac7179ac4f1048a5312d97f210c8362111dafb71e289b403f56':
        raise ValueError('Pinned DarwinBoot Entry.S changed')
    replacement=(HERE/'LoaderEntry.S').read_bytes()
    entry.write_bytes(replacement)
    metadata['loader_entry_change']={
        'before_sha256':before,'after_sha256':hashlib.sha256(replacement).hexdigest(),
        'maintenance':'kernel window and executing handoff to PoC before MMU/cache off'}
    return metadata


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uefi',type=Path,required=True)
    parser.add_argument('--dtb',type=Path,required=True)
    parser.add_argument('--core',type=Path,required=True)
    args=parser.parse_args()
    report=firmware(args.uefi.resolve(),args.dtb.resolve())
    report['shared_ramdisk']=shared_ramdisk(args.core.resolve())
    print(json.dumps(report,indent=2))
