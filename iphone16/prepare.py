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
    diag = root / 'pexpert/arm/k70_formal_diag.c'
    diag.write_text(replace_once(diag.read_text(),
        'PE_init_platform(FALSE) returned; native XNU C',
        'iOS16 ROOTCHAIN: original HFS / md0; hardware PMU unsupported').replace(
        ' K70 FORMAL XNU  diagnostic-3 ', ' K70 iOS16 ROOTCHAIN  HFS/md0 '))
    text = diag.read_text()
    text = replace_once(text, 'extern volatile uint32_t armcpu_gic_ready;',
        'extern volatile uint32_t k70_cpu_start_phase;\n'
        'volatile uint64_t k70_first_irq_pc, k70_first_irq_cpsr, k70_first_irq_sp;\n'
        'static volatile unsigned k70_first_irq_claim;\nextern volatile uint32_t armcpu_gic_ready;')
    # Declarations precede boot_progress_irq as well as the late summary.
    declarations_start = text.index('extern volatile uint32_t k70_cpu_start_phase;')
    declarations_end = text.index('extern volatile uint32_t armcpu_gic_ready;', declarations_start)
    declarations = text[declarations_start:declarations_end]
    text = text[:declarations_start] + text[declarations_end:]
    text = declarations + text
    text = replace_once(text, '\t__atomic_add_fetch(&g_state.irqs, 1, __ATOMIC_RELAXED);',
        '\tunsigned unclaimed = 0;\n'
        '\tif (__atomic_compare_exchange_n(&k70_first_irq_claim, &unclaimed, 1, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED)) {\n'
        '\t\tk70_first_irq_pc = pc; k70_first_irq_cpsr = cpsr; k70_first_irq_sp = sp;\n\t}\n'
        '\t__atomic_add_fetch(&g_state.irqs, 1, __ATOMIC_RELAXED);')
    text = replace_once(text, '    boot_progress_stage("root-device lookup next; no system root configured in this candidate");',
        '    k70_formal_cpu_trace("late CPU start phase", k70_cpu_start_phase);\n'
        '    k70_formal_cpu_trace("first IRQ PC", k70_first_irq_pc);\n'
        '    k70_formal_cpu_trace("first IRQ CPSR", k70_first_irq_cpsr);\n'
        '    k70_formal_cpu_trace("first IRQ SP", k70_first_irq_sp);\n'
        '    boot_progress_stage("root lookup next; rd=md0 requested, mount unverified");')
    # uint64_t is supplied by the observer's own headers before declarations.
    text = '#include <stdint.h>\n' + text
    diag.write_text(text)
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
    edit(root, name, "\t\trootdevice[0] = '\\0';",
         '\t\t{ extern void k70_formal_cpu_trace(const char *, uint64_t);'
         ' k70_formal_cpu_trace("vfs_mountroot failed err", (uint64_t)(int64_t)err); }\n'
         "\t\trootdevice[0] = '\\0';\n")
    # The root mount reports which stage and which filesystem refused, so a bare
    # errno can be attributed instead of guessed.
    name = "bsd/vfs/vfs_subr.c"
    edit(root, name, "\tbdevvp_rootvp = rootvp;",
         "\t{ extern void k70_formal_cpu_trace(const char *, uint64_t);\n"
         "\t  k70_formal_cpu_trace(\"mountroot bdevvp ok dev\", (uint64_t)rootdev); }\n"
         "\tbdevvp_rootvp = rootvp;")
    # The root mount reaches MACF after a successful filesystem mount; name the
    # step that refuses so ENODEV is not the only thing on screen.
    # One line per filesystem that refused the root, named after the filesystem
    # itself: the trace label is vfc_name, so "apfs value=0x13" is unambiguous.
    edit(root, "bsd/vfs/vfs_subr.c", "\t\tvfs_rootmountfailed(mp);",
         "\t\t{ extern void k70_formal_cpu_trace(const char *, uint64_t);\n"
         "\t\t  k70_formal_cpu_trace(vfsp->vfc_name, (uint64_t)(int64_t)error); }\n"
         "\t\tvfs_rootmountfailed(mp);")
    edit(root, 'bsd/kern/kern_exec.c', 'load_init_program(proc_t p)\n{',
         'load_init_program(proc_t p)\n{\n'
         '\t{ extern volatile uint32_t k70_stage; k70_stage = 7; }\n'
         '\tboot_progress_stage("load_init_program enter");')
    edit(root, 'bsd/kern/kern_exec.c',
         '\t(void) mach_vm_allocate_kernel(map, &scratch_addr, map_page_size, VM_FLAGS_ANYWHERE, VM_KERN_MEMORY_NONE);',
         '\t(void) mach_vm_allocate_kernel(map, &scratch_addr, map_page_size, VM_FLAGS_ANYWHERE, VM_KERN_MEMORY_NONE);\n'
         '\t{ extern volatile uint32_t k70_stage; k70_stage = 8; }')
    edit(root, 'bsd/kern/kern_exec.c',
         '\t(void) memorystatus_init_at_boot_snapshot();',
         '\t(void) memorystatus_init_at_boot_snapshot();\n'
         '\t{ extern volatile uint32_t k70_stage; k70_stage = 9; }')
    mark = '{ extern volatile uint32_t k70_stage; k70_stage = %d; }'
    edit(root, 'bsd/kern/kern_exec.c',
         '\tint retval[2];\n\tint error;\n\tstruct execve_args init_exec_args;\n\tuser_addr_t argv0 = USER_ADDR_NULL, argv1 = USER_ADDR_NULL;',
         '\t' + (mark % 10) + '\n'
         '\tint retval[2];\n\tint error;\n\tstruct execve_args init_exec_args;\n\tuser_addr_t argv0 = USER_ADDR_NULL, argv1 = USER_ADDR_NULL;')
    edit(root, 'bsd/kern/kern_exec.c',
         '\tscratch_addr = USER_ADDR_ALIGN(scratch_addr + path_length, sizeof(user_addr_t));',
         '\t' + (mark % 11) + '\n'
         '\tscratch_addr = USER_ADDR_ALIGN(scratch_addr + path_length, sizeof(user_addr_t));')
    edit(root, 'bsd/kern/kern_exec.c',
         '\tset_security_token(p);',
         '\t' + (mark % 12) + '\n\tset_security_token(p);\n\t' + (mark % 13))
    # After the clear, look at where the init thread actually sits: its state,
    # the run queue it belongs to and the processor it is bound to. A thread
    # parked on a processor that never came online never runs, and one CPU is
    # registered on this port.
    edit(root, 'osfmk/kern/task.c',
         '\tis_write_unlock(task->itk_space);\n\t}\n}\n\nvoid __attribute__((noreturn))',
         '\tis_write_unlock(task->itk_space);\n\t}\n'
         '\t{ extern void k70_formal_cpu_trace(const char *, uint64_t);\n'
         '\t  thread_t k70t;\n'
         '\t  queue_iterate(&task->threads, k70t, thread_t, task_threads) {\n'
         '\t\t  k70_formal_cpu_trace("P3 thread state", (uint64_t)(unsigned)k70t->state);\n'
         '\t\t  k70_formal_cpu_trace("P3 thread runq", (uint64_t)(unsigned long)k70t->runq);\n'
         '\t\t  k70_formal_cpu_trace("P3 thread bound", (uint64_t)(unsigned long)k70t->bound_processor);\n'
         '\t\t  k70_formal_cpu_trace("P3 thread last cpu",\n'
         '\t\t      (uint64_t)(k70t->last_processor ? (unsigned)k70t->last_processor->cpu_id : 0xffu));\n'
         '\t\t  k70_formal_cpu_trace("P4 thread sched pri", (uint64_t)(int64_t)k70t->sched_pri);\n'
         '\t\t  k70_formal_cpu_trace("P4 runq cpu id",\n'
         '\t\t      (uint64_t)(k70t->runq ? (unsigned)k70t->runq->cpu_id : 0xffu));\n'
         '\t\t  k70_formal_cpu_trace("P4 this cpu id", (uint64_t)(unsigned)current_processor()->cpu_id);\n'
         '\t\t  k70_formal_cpu_trace("P4 runq active pri",\n'
         '\t\t      (uint64_t)(k70t->runq && k70t->runq->active_thread ?\n'
         '\t\t          (int64_t)k70t->runq->active_thread->sched_pri : -1));\n'
         '\t\t  break;\n'
         '\t  } }\n}\n\nvoid __attribute__((noreturn))')

    # The wake is the suspect now: print the event the thread slept on, the
    # event that is woken, and how many threads the wakeup actually released.
    edit(root, 'osfmk/kern/task.c',
         '\tif (flags & TCRW_CLEAR_INITIAL_WAIT) {\n\t\tthread_wakeup(task_get_return_wait_event(task));',
         '\tif (flags & TCRW_CLEAR_INITIAL_WAIT) {\n'
         '\t\t{ extern void k70_formal_cpu_trace(const char *, uint64_t);\n'
         '\t\t  extern void *k70_pid1_task; k70_pid1_task = (void *)task;\n'
         '\t\t  extern volatile uint32_t k70_f0, k70_f2, k70_f3, k70_f5;\n'
         '\t\t  extern volatile int32_t k70_f1;\n'
         '\t\t  k70_f0 = task->t_returnwaitflags;\n'
         '\t\t  int k70woke = thread_wakeup(task_get_return_wait_event(task));\n'
         '\t\t  k70_f1 = k70woke;\n'
         '\t\t  k70_formal_cpu_trace("P2 wake event", (uint64_t)(unsigned long)task_get_return_wait_event(task));\n'
         '\t\t  k70_formal_cpu_trace("P2 woke threads", (uint64_t)(unsigned)k70woke);\n'
         '\t\t  k70_formal_cpu_trace("P2 returnwait flags", (uint64_t)task->t_returnwaitflags); }')
    # F5: the flags just before the FINAL branch finishes.
    edit(root, 'osfmk/kern/task.c',
         '\t\t\tturnstile_cleanup();\n\t\t\ttask->t_returnwaitflags &= ~TRW_LRETURNWAITER;',
         '\t\t\tk70_f5 = task->t_returnwaitflags;\n'
         '\t\t\tturnstile_cleanup();\n\t\t\ttask->t_returnwaitflags &= ~TRW_LRETURNWAITER;')
    # Stages 20 to 24: how far the fault gets. vm_fault itself is entered, so the
    # question is which wait inside it never returns.
    edit(root, 'osfmk/vm/vm_fault.c',
         '\tfault_type = original_fault_type;\n\tmap = original_map;\n\tvm_map_lock_read(map);',
         '\tfault_type = original_fault_type;\n\tmap = original_map;\n\tvm_map_lock_read(map);\n'
         '\t{ extern volatile uint32_t k70_stage; k70_stage = 20; }')
    edit(root, 'osfmk/vm/vm_fault.c',
         '\tvm_object_paging_begin(object);\n\n\tset_thread_pagein_error(cthread, 0);',
         '\tvm_object_paging_begin(object);\n'
         '\t{ extern volatile uint32_t k70_stage; k70_stage = 21; }\n\n\tset_thread_pagein_error(cthread, 0);')
    # 25/26: the shared-to-exclusive upgrade that a write fault needs.
    edit(root, 'osfmk/vm/vm_fault.c',
         '\t\tif (object_lock_type == OBJECT_LOCK_SHARED) {\n\t\t\tobject_lock_type = OBJECT_LOCK_EXCLUSIVE;',
         '\t\t{ extern volatile uint32_t k70_stage; k70_stage = 25; }\n'
         '\t\tif (object_lock_type == OBJECT_LOCK_SHARED) {\n\t\t\tobject_lock_type = OBJECT_LOCK_EXCLUSIVE;')
    edit(root, 'osfmk/vm/vm_fault.c',
         '\t\t\tif (vm_object_lock_upgrade(object) == FALSE) {\n\t\t\t\t/*\n\t\t\t\t * couldn\'t upgrade, so explictly',
         '\t\t\t{ extern volatile uint32_t k70_stage; k70_stage = 26; }\n'
         '\t\t\tif (vm_object_lock_upgrade(object) == FALSE) {\n\t\t\t\t/*\n\t\t\t\t * couldn\'t upgrade, so explictly')
    # The user pmap bounds decide whether the page table walk can ever succeed:
    # pmap_ttne rejects any address outside [min, max). A zero max makes every
    # walk fail, the expand loop retry forever and the page table pages run out.
    edit(root, 'osfmk/arm/pmap/pmap.c',
         '\tp->max = pmap_user_va_size(p);',
         '\tp->max = pmap_user_va_size(p);\n'
         '\t{ extern volatile uint64_t k70_va_bits, k70_va_max;\n'
         '\t  k70_va_bits = (uint64_t)pmap_user_va_bits(p); k70_va_max = (uint64_t)p->max;\n'
         '\t  if (p->max == 0) { p->max = (1ULL << (64 - T0SZ_BOOT)); k70_va_max = (uint64_t)p->max; } }')
    # 35: count the expand retries and keep the last status. A loop that expands
    # successfully but still finds no pte spins forever with every counter frozen.
    edit(root, 'osfmk/arm/pmap/pmap.c',
         '\t\tkr = pmap_expand(pmap, v, options, pt_attr_leaf_level(pt_attr));',
         '\t\t{ extern volatile uint32_t k70_tt_fail; k70_tt_fail++; }\n'
         '\t\tkr = pmap_expand(pmap, v, options, pt_attr_leaf_level(pt_attr));\n'
         '\t\t{ extern volatile uint32_t k70_tt_pre; k70_tt_pre = (uint32_t)kr; }')
    # 34: the page table allocation that fails and then waits forever.
    edit(root, 'osfmk/arm/pmap/pmap.c',
         '\t\t\twhile (pmap_tt_allocate(pmap, &tt_p, ttlevel + 1, ((options & PMAP_TT_ALLOCATE_NOWAIT)? PMAP_PAGES_ALLOCATE_NOWAIT : 0)) != KERN_SUCCESS) {',
         '\t\t\twhile (pmap_tt_allocate(pmap, &tt_p, ttlevel + 1, ((options & PMAP_TT_ALLOCATE_NOWAIT)? PMAP_PAGES_ALLOCATE_NOWAIT : 0)) != KERN_SUCCESS) {\n'
         '\t\t\t\t{ extern volatile uint32_t k70_tt_fail, k70_tt_pre, k70_stage;\n'
         '\t\t\t\t  k70_tt_fail++; k70_tt_pre = (uint32_t)preemption_enabled(); k70_stage = 34; }')
    # 32: the copy-on-write page grab inside the fast path, which asks the free
    # list for a page and can block there.
    edit(root, 'osfmk/vm/vm_fault.c',
         '\t\t\tcur_m = m;\n\t\t\tm = vm_page_grab_options(grab_options);',
         '\t\t\tcur_m = m;\n'
         '\t\t\t{ extern volatile uint32_t k70_stage; k70_stage = 32; }\n'
         '\t\t\tm = vm_page_grab_options(grab_options);')
    # 30/31: pmap_enter takes its own lock and may expand the page tables first.
    edit(root, 'osfmk/arm/pmap/pmap.c',
         '\tif (!pmap_lock_preempt(pmap, lock_mode)) {\n\t\treturn KERN_ABORTED;',
         '\t{ extern volatile uint32_t k70_stage; k70_stage = 30;\n'
         '\t  extern volatile uint64_t k70_pv, k70_pmin, k70_pmax;\n'
         '\t  extern volatile uint32_t k70_plevel, k70_proot;\n'
         '\t  k70_pv = (uint64_t)v; k70_pmin = (uint64_t)pmap->min; k70_pmax = (uint64_t)pmap->max;\n'
         '\t  k70_plevel = pt_attr_leaf_level(pt_attr); k70_proot = pt_attr->pta_root_level; }\n'
         '\tif (!pmap_lock_preempt(pmap, lock_mode)) {\n\t\treturn KERN_ABORTED;')
    edit(root, 'osfmk/arm/pmap/pmap.c',
         '\twhile ((pte_p = pmap_pte(pmap, v)) == PT_ENTRY_NULL) {',
         '\t{ extern volatile uint32_t k70_stage; k70_stage = 31; }\n'
         '\twhile ((pte_p = pmap_pte(pmap, v)) == PT_ENTRY_NULL) {')
    # 27: the paging reference taken just before the fast path hands the page to
    # pmap; 28: entering vm_fault_enter itself.
    edit(root, 'osfmk/vm/vm_fault.c',
         '\t\tm = vm_page_lookup(cur_object, vm_object_trunc_page(cur_offset));',
         '\t\t{ extern volatile uint32_t k70_stage; k70_stage = 27; }\n'
         '\t\tm = vm_page_lookup(cur_object, vm_object_trunc_page(cur_offset));')
    edit(root, 'osfmk/vm/vm_fault.c',
         '\t\t\t\tif (caller_pmap) {\n\t\t\t\t\tk r = vm_fault_enter(m,'.replace('\tk r','\tkr'),
         '\t\t\t\t{ extern volatile uint32_t k70_stage; k70_stage = 28; }\n\t\t\t\tif (caller_pmap) {\n\t\t\t\t\tkr = vm_fault_enter(m,')
    edit(root, 'osfmk/vm/vm_fault.c',
         '\t\t\t\tif (caller_pmap) {\n\t\t\t\t\tkr = vm_fault_enter(m,',
         '\t\t\t\t{ extern volatile uint32_t k70_stage; k70_stage = 28; }\n'
         '\t\t\t\tif (caller_pmap) {\n\t\t\t\t\tkr = vm_fault_enter(m,')
    # The lookup is the last thing before 21, so mark its result explicitly.
    edit(root, 'osfmk/vm/vm_fault.c',
         '\t    &real_map,\n\t    &object_is_contended);',
         '\t    &real_map,\n\t    &object_is_contended);\n'
         '\t{ extern volatile uint32_t k70_stage, k70_fault_kr; k70_fault_kr = (uint32_t)kr; k70_stage = 24; }')
    edit(root, 'osfmk/vm/vm_fault.c',
         '\tresult_page = VM_PAGE_NULL;\n\tkr = vm_fault_page(object, offset, fault_type,',
         '\tresult_page = VM_PAGE_NULL;\n'
         '\t{ extern volatile uint32_t k70_stage; k70_stage = 22; }\n'
         '\tkr = vm_fault_page(object, offset, fault_type,')
    edit(root, 'osfmk/vm/vm_fault.c',
         '\t    &error_code, map->no_zero_fill,\n\t    &fault_info);',
         '\t    &error_code, map->no_zero_fill,\n\t    &fault_info);\n'
         '\t{ extern volatile uint32_t k70_stage; k70_stage = 23; }')
    # Count the faults: the copyout into the new task hangs, and a fault storm at
    # one address and no fault at all mean very different things.
    edit(root, 'osfmk/vm/vm_fault.c',
         '\treturn vm_fault_internal(map, vaddr, fault_type, change_wiring, wire_tag,',
         '\t{ extern volatile uint32_t k70_faults; extern volatile uint64_t k70_fault_addr;\n'
         '\t  k70_faults++; k70_fault_addr = (uint64_t)vaddr; }\n'
         '\treturn vm_fault_internal(map, vaddr, fault_type, change_wiring, wire_tag,')
    # F2/F3: what the flags look like around the clear in the FINAL branch.
    edit(root, 'osfmk/kern/task.c',
         '\t\ttask->t_returnwaitflags &= ~TRW_LRETURNWAIT;',
         '\t\tk70_f2 = task->t_returnwaitflags;\n'
         '\t\ttask->t_returnwaitflags &= ~TRW_LRETURNWAIT;\n'
         '\t\tk70_f3 = task->t_returnwaitflags;')
    # Does the scheduler ever receive this thread? A runnable thread that the
    # run queue never sees and one that is inserted but never chosen need
    # different fixes, and only a counter in thread_setrun tells them apart.
    edit(root, 'osfmk/kern/sched_prim.c',
         '\tprocessor_t                     processor = PROCESSOR_NULL;\n\tprocessor_set_t         pset;',
         '\tprocessor_t                     processor = PROCESSOR_NULL;\n\tprocessor_set_t         pset;\n'
         '\t{ extern void k70_formal_cpu_trace(const char *, uint64_t);\n'
         '\t  extern void *k70_pid1_task;\n'
         '\t  static unsigned k70_setrun_hits;\n'
         '\t  if (k70_pid1_task && (void *)thread->t_tro->tro_task == k70_pid1_task) {\n'
         '\t\t  k70_setrun_hits++;\n'
         '\t\t  if (k70_setrun_hits <= 3) {\n'
         '\t\t\t  k70_formal_cpu_trace("P5 setrun pid1", (uint64_t)k70_setrun_hits); } } }')
    # B: the wait and the block results, counted where the init thread waits.
    edit(root, 'osfmk/kern/task.c',
         '\t\t\twaitq_assert_wait64(&turnstile->ts_waitq,',
         '\t\t\tk70_b_iter++;\n'
         '\t\t\twait_result_t k70_wr = waitq_assert_wait64(&turnstile->ts_waitq,')
    edit(root, 'osfmk/kern/task.c',
         '\t\t\t    THREAD_UNINT, TIMEOUT_WAIT_FOREVER);',
         '\t\t\t    THREAD_UNINT, TIMEOUT_WAIT_FOREVER);\n'
         '\t\t\tk70_b_wr = (int32_t)k70_wr;')
    edit(root, 'osfmk/kern/task.c',
         '\t\t\tthread_block(THREAD_CONTINUE_NULL);',
         '\t\t\tk70_b_br = (int32_t)thread_block(THREAD_CONTINUE_NULL);')
    # The init thread's first continuation is task_wait_to_return, not
    # bsdinit_task. One line here answers whether it starts executing at all,
    # without reading a Mach-private structure from a BSD file.
    p = root / 'osfmk/kern/task.c'
    p.write_text('#include <kern/boot_progress.h>\n'
                 'void *k70_pid1_task;\n'
                 'volatile uint32_t k70_pid1_ran;\n'
                 'volatile uint32_t k70_f0, k70_f2, k70_f3, k70_f5;\n'
                 'volatile int32_t k70_f1;\n'
                 'volatile uint32_t k70_b_iter;\n'
                 'volatile int32_t k70_b_wr, k70_b_br;\n' 
                 'volatile uint32_t k70_p6, k70_p7, k70_p8, k70_bsd;\n' 
                 'volatile uint32_t k70_stage, k70_exec_errno;\n'
                 'volatile uint32_t k70_faults, k70_fault_kr;\n'
                 'volatile uint32_t k70_tt_fail, k70_tt_pre;\n'
                 'volatile uint64_t k70_pv, k70_pmin, k70_pmax;\n'
                 'volatile uint32_t k70_plevel, k70_proot, k70_pdump;\n'
                 'volatile uint64_t k70_va_bits, k70_va_max;\n'
                 'volatile uint64_t k70_fault_addr;\n' + p.read_text())
    edit(root, 'osfmk/kern/task.c',
         '\tis_write_lock(task->itk_space);\n\n\tif (task->t_returnwaitflags & TRW_LRETURNWAIT) {',
         '\tis_write_lock(task->itk_space);\n\tk70_p6 = 1;\n\n\tif (task->t_returnwaitflags & TRW_LRETURNWAIT) {')
    edit(root, 'osfmk/kern/task.c',
         '\tis_write_unlock(task->itk_space);\n\tturnstile_cleanup();',
         '\tk70_p7 = 1;\n\tis_write_unlock(task->itk_space);\n\tturnstile_cleanup();')
    edit(root, 'osfmk/kern/task.c',
         '\tthread_bootstrap_return();\n}',
         '\tk70_p8 = 1;\n\tthread_bootstrap_return();\n}')
    edit(root, 'osfmk/kern/task.c', 'task_wait_to_return(void)\n{',
         'task_wait_to_return(void)\n{\n'
         '\t{ extern volatile uint32_t k70_pid1_ran; k70_pid1_ran = 1; }\n'
         '\tboot_progress_stage("P1 task_wait_to_return enter");')
    # BSD: bsdinit_task reached, which is the last boundary before launchd.
    edit(root, 'bsd/kern/bsd_init.c', 'bsdinit_task(void)\n{',
         'bsdinit_task(void)\n{\n\t{ extern volatile uint32_t k70_bsd; k70_bsd = 1; }\n'
         '\tboot_progress_stage("Q0 bsdinit_task enter");')
    name = 'iokit/bsddev/IOKitBSDInit.cpp'
    path = root / name
    path.write_text('extern "C" {\n#include <kern/boot_progress.h>\n}\n' + path.read_text())
    edit(root, name, '\t// stall here for anyone matching on the IOBSD resource to finish (filesystems)',
         '\tboot_progress_stage("IOFindBSDRoot enter; IOBSD wait next");\n'
         '\t// stall here for anyone matching on the IOBSD resource to finish (filesystems)')
    edit(root, name, '\tif (mountAttempts++) {',
         '\tboot_progress_stage("IOBSD wait returned; RAMDisk lookup next");\n\tif (mountAttempts++) {')
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
    from flight_patch import install as install_flight
    install_flight(root)
    from storage_bootstrap import install as install_storage
    install_storage(root)
    import importlib.util
    ufs_spec = importlib.util.spec_from_file_location('k70_ufs_install', HERE / 'ufs/install.py')
    ufs_install = importlib.util.module_from_spec(ufs_spec)
    ufs_spec.loader.exec_module(ufs_install)
    ufs_install.install(root)
    from kext_logging import install as install_kext_logging
    install_kext_logging(root)
    from userspace_bootstrap import install as install_userspace
    install_userspace(root)


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
                  'makedefs/MakeInc.kernel', 'makedefs/MakeInc.rule', 'makedefs/MakeInc.def', 'osfmk/kern/Makefile', 'osfmk/kern/ast.c', 'osfmk/arm64/start.s', 'pexpert/arm/pe_serial.c',
                  'osfmk/arm/arm_init.c', 'osfmk/kern/startup.c', 'osfmk/console/video_console.c',
                  'osfmk/console/serial_console.c', 'pexpert/arm/pe_kprintf.c', 'bsd/kern/bsd_init.c',
                  'osfmk/arm64/sleh.c', 'bsd/kern/kern_exec.c', 'bsd/kern/kern_ktrace.c',
                  'iokit/bsddev/IOKitBSDInit.cpp', 'bsd/kern/kern_fork.c',
                  'bsd/dev/arm/systemcalls.c', 'osfmk/arm64/bsd_arm64.c',
                  'iokit/Kernel/IOCPU.cpp', 'osfmk/kern/debug.c', 'bsd/vfs/vfs_subr.c', 'bsd/vfs/kpi_vfs.c',
                  'osfmk/arm64/pcb.c', 'osfmk/kern/sched_prim.c', 'osfmk/kern/processor.c',
                  'osfmk/kern/task.c', 'osfmk/vm/vm_fault.c', 'osfmk/arm/pmap/pmap.c'))
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
    backend = HERE / 'upstream/NoPmuKpc.c'
    if hashlib.sha256(backend.read_bytes()).hexdigest() != '3d024d8d896c4127d6e36c4daa8cb8ff048b5faf04522b127450b0471b87f9b6':
        raise ValueError('Unreviewed no-PMU backend')
    target = staging / 'osfmk/arm64/kpc.c'
    if target.exists():
        raise ValueError('Refusing to replace an existing KPC implementation')
    target.write_bytes(backend.read_bytes())
    p = staging / 'osfmk/conf/files.arm64'
    p.write_text(''.join(line.rstrip('\n') + (' apple_amcc' if re.match(r'osfmk/arm64/amcc_rorgn_.* optional ', line) else '') + '\n' for line in p.read_text().splitlines(True)))
    edit(staging, 'makedefs/MakeInc.kernel', '$(TARGET)/$(KERNEL_FILE_NAME).unstripped: $(addprefix',
         '$(TARGET)/$(KERNEL_FILE_NAME).unstripped: $(XNU_EXTERNAL_KERNEL_ARCHIVES)\n\n$(TARGET)/$(KERNEL_FILE_NAME).unstripped: $(addprefix')
    # Backport the real compiler record emission used by XNU23. The archive
    # builders must inherit the exact generated C/C++ ABI, not guessed flags.
    rules = staging / 'makedefs/MakeInc.rule'
    text = rules.read_text()
    if text.count('-MF $(@:o=d) -MP') != 3:
        raise ValueError('Unexpected XNU22 C/C++/assembly record rules')
    rules.write_text(text.replace('-MF $(@:o=d) -MP',
        '-MF $(@:o=d) -MJ $(@:o=o.json) -MP'))
    # XNU22 otherwise silently ignores the UniXNU recipe's provider/board
    # defines. Match the newer build interface without changing their values.
    edit(staging, 'makedefs/MakeInc.def', 'CFLAGS\t= $(CFLAGS_GEN) \\\n',
         'CFLAGS\t= $(CFLAGS_GEN) $(CFLAGS_EXTRA) \\\n')
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
    shutil.copy2(HERE / 'cpu_start_trace.py', tree / 'scripts/iphone16_cpu_start_trace.py')
    # Original device recipe is read through git, independent of local edits.
    original = subprocess.check_output(['git', '-C', str(device), 'show', DEVICE + ':scripts/build-arm-driver.py'], text=True)
    if hashlib.sha256(original.encode()).hexdigest() != '7d520749568581c3cf741e732f53d0553f66344b5cda3a473c3d12822a344d40':
        raise ValueError('Unexpected original CPU archive builder')
    anchor = 'source = ROOT / "drivers" / component / (component + ".cpp")'
    original = replace_once(original, anchor, anchor + '\nif component == "ArmCpu":\n    from k70_macho_asm import prepare_armcpu_source\n    from iphone16_cpu_start_trace import prepare as prepare_start_trace\n    source = prepare_start_trace(prepare_armcpu_source(source, ROOT / ".cache/k70-armcpu"))')
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
