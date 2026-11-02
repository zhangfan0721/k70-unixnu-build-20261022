"""Exercise the real backend body; fixtures are not a kernel ABI proof."""
import re
import subprocess


def check(out, backend, deployment):
    headers = out / 'pmu-fixture'
    declarations = '''#pragma once
typedef unsigned int uint32_t;
typedef unsigned long long uint64_t;
typedef int boolean_t;
typedef uint64_t kpc_config_t;
struct kpc_config_remote;
struct kpc_running_remote;
#define FALSE 0
#define KPC_PMU_ERROR 0
#define ENOTSUP 45
#define __unused __attribute__((unused))
int cpu_number(void);
'''
    for name in ('mach/mach_types.h', 'machine/machine_routines.h',
                 'kern/processor.h', 'sys/errno.h', 'kern/kpc.h'):
        path = headers / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(declarations if name == 'mach/mach_types.h' else '')
    obj = out / 'no-pmu-ios16.o'
    subprocess.run(['clang', '--target=arm64-apple-ios16.0', '-ffreestanding',
        '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(headers),
        '-c', str(backend), '-o', str(obj)], check=True)
    deployment(obj)
    asm = subprocess.check_output(['llvm-objdump', '-d', str(obj)], text=True)
    (out / 'no-pmu-disassembly.txt').write_text(asm)
    if re.search(r'\b(?:mrs|msr|sys|sysl)\b', asm):
        raise ValueError('Unexpected privileged register access in no-PMU backend')
    test = out / 'no-pmu-contract.c'
    test.write_text('#include "' + backend.resolve().as_posix() + '"\n' + '''
int cpu_number(void) { return 7; }
#define CHECK(x) do { if (!(x)) return __LINE__; } while (0)
int main(void) {
 uint64_t value = 0xdeadbeefULL;
 int cpu = -1;
 kpc_arch_init(); kpc_idle(); kpc_idle_exit();
 CHECK(kpc_get_classes() == 0 && kpc_get_pmu_version() == KPC_PMU_ERROR);
 CHECK(kpc_fixed_count() == 0 && kpc_fixed_config_count() == 0 && kpc_fixed_max() == 0);
 CHECK(kpc_configurable_count() == 0 && kpc_configurable_config_count(~0ULL) == 0);
 CHECK(kpc_configurable_max() == 0 && kpc_rawpmu_config_count() == 0);
 CHECK(!kpc_is_running_fixed() && !kpc_is_running_configurable(~0ULL));
 CHECK(kpc_set_config_arch(0) == ENOTSUP && kpc_set_period_arch(0) == ENOTSUP);
 CHECK(kpc_set_running_arch(0) == ENOTSUP && kpc_set_sw_inc(~0U) == ENOTSUP);
 CHECK(kpc_get_rawpmu_config(&value) == 0 && kpc_get_fixed_config(&value) == 0);
 CHECK(kpc_get_fixed_counters(&value) == 0);
 CHECK(kpc_get_configurable_config(&value, ~0ULL) == 0);
 CHECK(kpc_get_configurable_counters(&value, ~0ULL) == 0);
 CHECK(kpc_get_all_cpus_counters(~0U, &cpu, &value) == 0 && cpu == 7);
 CHECK(kpc_get_all_cpus_counters(~0U, 0, &value) == 0);
 CHECK(value == 0xdeadbeefULL);
 return 0;
}
''')
    executable = out / 'no-pmu-contract'
    subprocess.run(['clang', '-Wall', '-Wextra', '-Werror', '-I', str(headers),
        str(test), '-o', str(executable)], check=True)
    subprocess.run([str(executable.resolve())], check=True)
