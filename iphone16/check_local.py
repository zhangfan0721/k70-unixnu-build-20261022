"""Check fixed-source patch application and actual iOS16 Mach-O instructions."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
from check_sources import check as check_source_inputs

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
    presence = check_source_inputs(args.source, args.out / 'patched')
    (args.out / 'source-presence.json').write_text(json.dumps(presence, indent=2) + '\n')
    if presence['missing'] or not presence['kpc_enabled'] or not presence['kperf_enabled']:
        raise ValueError('Selected source configuration includes unavailable inputs: ' + str(presence))
    from check_records import check as check_records
    check_records(args.out / 'patched/makedefs/MakeInc.rule', args.source_device,
                  args.core, args.out / 'compile-record-check')
    from check_vfsops import check as check_vfsops
    vfsops = check_vfsops(args.source, args.out / 'patched', args.out, deployment)
    # Restore the original sampling call sites as a group, not more guards for
    # a disabled configuration that the actual iOS target does not use.
    restored = ('osfmk/kern/ast.c', 'osfmk/arm64/pcb.c',
                'osfmk/kern/sched_prim.c', 'osfmk/kern/processor.c',
                'bsd/kern/kern_ktrace.c')
    for name in restored:
        patched_sampling = (args.out / 'patched' / name).read_text()
        if name == 'osfmk/kern/sched_prim.c':
            patched_sampling = patched_sampling.replace('#include <kern/K70Flight.h>\n', '', 1)
            hook = ('\tif (self->state & TH_WAIT) k70_flight_wait((uintptr_t)self, (uintptr_t)self->wait_event, self->state,\n'
                    '\t    (uintptr_t)__builtin_return_address(0), (uintptr_t)__builtin_frame_address(0));\n')
            if patched_sampling.count(hook) != 1:
                raise ValueError('Unexpected scheduler evidence hook')
            patched_sampling = patched_sampling.replace(hook, '', 1)
        if patched_sampling != (args.source / name).read_text():
            raise ValueError('Sampling source differs from pinned Apple original: ' + name)
    # Compile the actual enum/array/assertion for the enabled target.
    enum_text = re.search(r'enum running_timer \{.*?\n\};',
        (args.source / 'osfmk/kern/timer_call.h').read_text(), re.S)[0]
    table_text = re.search(r'static timer_call_func_t running_timer_funcs\[\] = \{.*?missing running timer function"\);',
        (args.out / 'patched/osfmk/kern/processor.c').read_text(), re.S)[0]
    table_source = args.out / 'running-timer-table.c'
    table_source.write_text('''typedef void (*timer_call_func_t)(void *, void *);
extern void thread_quantum_expire(void *, void *);
extern void kperf_timer_expire(void *, void *);
#define static_assert _Static_assert
''' + enum_text + '\n' + table_text + '''
unsigned k70_timer_table_count(void) {
 return sizeof(running_timer_funcs) / sizeof(running_timer_funcs[0]);
}
timer_call_func_t k70_timer_table_lookup(unsigned index) {
 return running_timer_funcs[index % RUNNING_TIMER_MAX];
}
''')
    for mode in (1,):
        obj = args.out / ('running-timer-table-' + str(mode) + '.o')
        subprocess.run(['clang', '--target=arm64-apple-ios16.0', '-std=c11', '-ffreestanding',
            '-Wall', '-Wextra', '-Werror', '-DKPERF=' + str(mode), '-c', str(table_source), '-o', str(obj)], check=True)
        deployment(obj)
    from check_no_pmu import check as check_no_pmu
    check_no_pmu(args.out, args.out / 'patched/osfmk/arm64/kpc.c', deployment)
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
    # Evaluate the real XNU22 Makefile's export list. Cross-component consumers
    # see EXPORT_HDRS, not an extra -I path into the osfmk source directory.
    query = args.out / 'header-query.mk'
    query.write_text('query:\n\t@echo $(EXPORT_MI_LIST)\n')
    names = subprocess.check_output(['make', '-s', '-f', str(args.out / 'patched/osfmk/kern/Makefile'),
        '-f', str(query), 'query', 'MakeInc_cmd=/dev/null', 'MakeInc_def=/dev/null',
        'MakeInc_rule=/dev/null', 'MakeInc_dir=/dev/null'], text=True).split()
    if 'boot_progress.h' not in names:
        raise ValueError('Diagnostic header missing from actual component exports')
    exported = args.out / 'EXPORT_HDRS/osfmk/kern'
    exported.mkdir(parents=True)
    shutil.copy2(args.out / 'patched/osfmk/kern/boot_progress.h', exported / 'boot_progress.h')
    shutil.copy2(args.out / 'patched/osfmk/kern/K70Flight.h', exported / 'K70Flight.h')
    obj = args.out / 'observer.o'
    src = args.out / 'observer.c'
    generated_observer = (args.out / 'patched/pexpert/arm/k70_formal_diag.c').read_text()
    adapter_start = generated_observer.index('/* SPDX-License-Identifier: BSD-2-Clause-Patent\n * Source-kernel adapter')
    src.write_text(generated_observer[:adapter_start].replace('#include "K70FlightKernel.c"', '#include <kern/K70Flight.h>'))
    subprocess.run(['clang', '--target=arm64-apple-ios16.0', '-std=c11', '-ffreestanding',
        '-fno-builtin', '-O0', '-Wall', '-Wextra', '-Werror', '-I', str(exported.parent),
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
        'generated_recipe_syntax_checked': True, 'actual_xnu_component_header_exports_checked': True,
        'selected_config_source_presence_checked': True,
        'actual_timer_enum_table_ios16_kperf_enabled_checked': True,
        'original_sampling_call_sites_restored': list(restored),
        'no_pmu_contract_and_ios16_object_checked': True,
        'real_compile_records_and_driver_consumer_checked': True,
        'vfsops_contract': vfsops,
        'full_kernel_compiled': False,
        'hardware_tested': False, 'original_component_abi_verified': False}
    (args.out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
