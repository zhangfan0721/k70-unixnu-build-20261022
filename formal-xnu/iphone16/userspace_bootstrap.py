"""Expose the real bootstrap/exec boundaries using the existing display path."""
from pathlib import Path
HERE=Path(__file__).resolve().parent

def install(root):
    def edit(name,before,after):
        p=root/name;s=p.read_text()
        if s.count(before)!=1:raise ValueError('Userspace anchor changed: '+before[:90])
        p.write_text(s.replace(before,after,1))
    name='bsd/kern/bsd_init.c'
    edit(name,'vfs_mountroot mounted; authentication pending','vfs_mountroot mounted; root policy check next')
    edit(name,'\tif (!bsd_rooted_ramdisk()) {',
        '\tbool k70_ram_root = bsd_rooted_ramdisk();\n'
        '\tboot_progress_stage(k70_ram_root ? "RAM root: original rootauth exception" : "system root: original rootauth required");\n'
        '\tif (!k70_ram_root) {')
    edit(name,'bsd_utaskbootstrap(void)\n{','bsd_utaskbootstrap(void)\n{\n\t{ extern volatile uint32_t k70_stage_mark; k70_stage_mark = 1; }\n\tboot_progress_stage("PID1 bootstrap enter; cloneproc next");')
    edit(name,'\tthread = cloneproc(TASK_NULL, NULL, kernproc, CLONEPROC_FLAGS_MEMSTAT_INTERNAL);',
        '\tthread = cloneproc(TASK_NULL, NULL, kernproc, CLONEPROC_FLAGS_MEMSTAT_INTERNAL);\n'
        '\tboot_progress_stage("PID1 cloneproc returned; proc_find next");')
    edit(name,'\tinitproc = proc_find(1);','\tinitproc = proc_find(1);\n\tboot_progress_stage("PID1 proc_find returned");')
    edit(name,'\ttask_clear_return_wait(get_threadtask(thread), TCRW_CLEAR_ALL_WAIT);',
        '\tboot_progress_stage("PID1 clear return wait enter");\n'
        '\ttask_clear_return_wait(get_threadtask(thread), TCRW_CLEAR_ALL_WAIT);\n'
        '\tboot_progress_stage("PID1 bootstrap returned");')
    edit(name,'bsdinit_task(void)\n{','bsdinit_task(void)\n{\n\t{ extern volatile uint32_t k70_stage_mark; k70_stage_mark = 2; }\n\tboot_progress_stage("PID1 bsdinit_task enter");')
    for idx,(call,label) in enumerate([('ux_handler_setup();','exception setup'),('vm_init_before_launchd();','VM before launchd')]):
        edit(name,'\t'+call,'\t{ extern volatile uint32_t k70_stage_mark; k70_stage_mark = 3 + '+str(idx)+'; }\n\tboot_progress_stage("PID1 '+label+' enter");\n\t'+call+'\n\tboot_progress_stage("PID1 '+label+' returned");')
    name='bsd/kern/kern_fork.c'
    p=root/name;p.write_text('#include <kern/boot_progress.h>\nextern void k70_formal_cpu_trace(const char *, uint64_t);\n'+p.read_text())
    edit(name,'\tresult = task_create_internal(parent_task,','\tif (parent_task == TASK_NULL) boot_progress_stage("PID1 task_create_internal enter");\n\tresult = task_create_internal(parent_task,')
    edit(name,'\t    child_task);\n\tif (result != KERN_SUCCESS)',
        '\t    child_task);\n\tif (parent_task == TASK_NULL) k70_formal_cpu_trace("PID1 task status", (uint32_t)result);\n\tif (result != KERN_SUCCESS)')
    edit(name,'\tresult = main_thread_create_waiting(child_task,','\tif (parent_task == TASK_NULL) boot_progress_stage("PID1 main_thread_create_waiting enter");\n\tresult = main_thread_create_waiting(child_task,')
    edit(name,'\t    &child_thread);','\t    &child_thread);\n\tif (parent_task == TASK_NULL) k70_formal_cpu_trace("PID1 thread status", (uint32_t)result);')
    edit(name,'bad:\n\tthread_yield_internal(1);','bad:\n\tif (parent_task == TASK_NULL) boot_progress_stage("PID1 creation yield enter");\n\tthread_yield_internal(1);\n\tif (parent_task == TASK_NULL) boot_progress_stage("PID1 creation yield returned");')
    name='bsd/kern/kern_exec.c'
    edit(name,'#include <kern/boot_progress.h>',
        '#include <kern/boot_progress.h>\nextern void k70_formal_cpu_trace(const char *, uint64_t);')
    edit(name,'\tlret = load_machfile(imgp, mach_header, thread, &map, &load_result);',
        '\tlret = load_machfile(imgp, mach_header, thread, &map, &load_result);\n'
        '\tif (proc_pid(p) == 1) {\n'
        '\t\tk70_formal_cpu_trace("PID1 Mach-O status", (uint32_t)lret);\n'
        '\t\tif (lret == LOAD_SUCCESS) {\n'
        '\t\t\tk70_formal_cpu_trace("PID1 prepared entry", load_result.entry_point);\n'
        '\t\t\tk70_formal_cpu_trace("PID1 dyld header", load_result.dynlinker_mach_header);\n'
        '\t\t\tk70_formal_cpu_trace("PID1 dyld end", load_result.dynlinker_max_vm_addr);\n\t\t}\n\t}')
    edit(name,'\treturn execve(p, &init_exec_args, retval);',
        '\t{ extern volatile uint32_t k70_stage_mark; k70_stage_mark = 9; }\n'
        '\tboot_progress_stage("PID1 execve enter");\n\tboot_progress_stage(path);\n'
        '\terror = execve(p, &init_exec_args, retval);\n'
        '\tk70_formal_cpu_trace("PID1 exec errno", (uint32_t)error);\n'
        '\tif (error) { boot_progress_stage("PID1 exec failed; halted"); for(;;) { __asm__ volatile("wfi"); } }\n'
        '\tboot_progress_stage("PID1 exec returned 0; entering userland");\n\treturn error;')
    p=root/name;s=p.read_text();start=s.index('\nload_init_program_at_path(');end=s.index('\nstatic const char * init_programs',start)
    body=s[start:end]
    if body.count('\t\treturn error;')!=4:raise ValueError('Initial exec copyout paths changed')
    body=body.replace('\t\treturn error;','\t\tk70_formal_cpu_trace("PID1 copyout errno", (uint32_t)error);\n\t\treturn error;')
    p.write_text(s[:start]+body+s[end:])
    declaration='extern void k70_user_trap(unsigned,int,uint64_t,uint64_t,uint64_t);\n'
    name='bsd/dev/arm/systemcalls.c';p=root/name;p.write_text('#include <stdint.h>\n'+declaration+p.read_text())
    edit(name,'\tcode = arm_get_syscall_number(state);',
        '\tk70_user_trap(0, proc_pid(proc), get_saved_state_pc(state), get_saved_state_cpsr(state), arm_get_syscall_number(state));\n\tcode = arm_get_syscall_number(state);')
    name='osfmk/arm64/bsd_arm64.c';p=root/name
    edit(name,'extern void throttle_lowpri_io(int);',declaration+'extern void throttle_lowpri_io(int);')
    edit(name,'\tint call_number = get_saved_state_svc_number(state);',
        '\tk70_user_trap(1, proc_pid(current_proc()), get_saved_state_pc(state), get_saved_state_cpsr(state), get_saved_state_svc_number(state));\n\tint call_number = get_saved_state_svc_number(state);')
    name='pexpert/arm/k70_formal_diag.c';p=root/name
    p.write_text(p.read_text()+'\n'+(HERE/'UserBootstrap.c').read_text())
