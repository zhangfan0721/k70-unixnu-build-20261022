"""Install the fixed, single-CPU panic/wait evidence path into a build copy."""
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent


def replace(text,before,after):
    if text.count(before)!=1:
        raise ValueError('Flight capture source anchor changed: '+before[:90])
    return text.replace(before,after,1)


def install(root):
    for name in ('K70FlightCore.h','K70FlightScreen.h','K70FlightKernel.c'):
        shutil.copy2(HERE/name,root/'pexpert/arm'/name)
    shutil.copy2(HERE/'K70Flight.h',root/'osfmk/kern/K70Flight.h')
    path=root/'osfmk/kern/Makefile'
    path.write_text(replace(path.read_text(),'\tboot_progress.h \\\n','\tboot_progress.h \\\n\tK70Flight.h \\\n'))
    path=root/'pexpert/arm/k70_formal_diag.c'
    text='#include "K70FlightKernel.c"\n'+path.read_text()
    text=replace(text,'#define BP_LOG_LINES    40','#define BP_LOG_LINES    32')
    # The normal observer never paints the emergency area. Repainting the full
    # emergency panel on every ordinary console update would perturb startup.
    text=replace(text,'\tg_screen.bound = 1;','''\tg_screen.bound = 1;
\tk70_flight_bind(framebuffer, width, height, rowbytes, depth);
\tunsigned normal_rows = k70_flight_log_height(height) / (14u * scale);
\tif (normal_rows < g_screen.rows) { g_screen.rows = normal_rows; }''')
    path.write_text(text)
    path=root/'iokit/Kernel/IOCPU.cpp'
    text='#include <kern/K70Flight.h>\n'+path.read_text()
    anchor='IOCPUInterruptController::initCPUInterruptController(int sources, int cpus)'
    start=text.index(anchor);end=text.index('\nvoid\nIOCPUInterruptController::registerCPUInterruptController',start)
    body=text[start:end]
    body=replace(body,'\tif (!super::init()) {','''\tk70_flight_enter(1, 0);
\tbool parent_initialized = super::init();
\tk70_flight_leave(1, parent_initialized);
\tif (!parent_initialized) {''')
    body=replace(body,'\tvectors = (IOInterruptVector *)zalloc_permanent',
                 '\tk70_flight_enter(2, numSources);\n\tvectors = (IOInterruptVector *)zalloc_permanent')
    body=replace(body,'\t    sizeof(IOInterruptVector), ZALIGN(IOInterruptVector));',
                 '\t    sizeof(IOInterruptVector), ZALIGN(IOInterruptVector));\n\tk70_flight_leave(2, (uintptr_t)vectors);')
    body=replace(body,'\t\tvectors[cnt].interruptLock = IOLockAlloc();',
                 '\t\tk70_flight_enter(3, cnt);\n\t\tvectors[cnt].interruptLock = IOLockAlloc();\n\t\tk70_flight_leave(3, (uintptr_t)vectors[cnt].interruptLock);')
    body=replace(body,'\tml_set_max_cpus(numSources);',
                 '\tk70_flight_enter(4, numSources);\n\tml_set_max_cpus(numSources);\n\tk70_flight_leave(4, 0);')
    text=text[:start]+body+text[end:];path.write_text(text)
    path=root/'osfmk/kern/debug.c'
    text='#include <kern/K70Flight.h>\n'+path.read_text()
    anchor='    uint64_t panic_options_mask, void *panic_data_ptr, unsigned long panic_caller)\n{'
    text=replace(text,anchor,anchor+'\n\tk70_flight_panic(panic_format_str, (uintptr_t)panic_caller, (uintptr_t)__builtin_frame_address(0));')
    path.write_text(text)
    path=root/'osfmk/kern/sched_prim.c'
    text='#include <kern/K70Flight.h>\n'+path.read_text()
    start=text.index('\nthread_block_reason(\n');end=text.index('\nwait_result_t\nthread_block_parameter',start)
    body=text[start:end]
    body=replace(body,'\tthread_t        self = current_thread();',
        '\tthread_t        self = current_thread();\n'
        '\tk70_flight_wait((uintptr_t)self, (uintptr_t)self->wait_event, self->state,\n'
        '\t    (uintptr_t)__builtin_return_address(0), (uintptr_t)__builtin_frame_address(0));')
    path.write_text(text[:start]+body+text[end:])
