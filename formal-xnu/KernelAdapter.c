/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Source-kernel adapter for the shared boot_progress hooks. No device MMIO
 * programming, storage access, or UEFI calls after ExitBootServices.
 */
#include <pexpert/pexpert.h>
#include <machine/machine_routines.h>
#include <kern/thread.h>
#include <kern/sched_prim.h>
#include <kern/clock.h>
#include <mach/thread_act.h>
#include "BootstrapMap.h"
#include <stddef.h>

_Static_assert(offsetof(boot_args, Video)==40, "early ASM boot video offset");
_Static_assert(sizeof(Boot_Video)==48, "early ASM ARM64 video layout");
_Static_assert(offsetof(Boot_Video, v_depth)==40, "early ASM depth offset");

static uint64_t k70_formal_fb_l2[512] __attribute__((aligned(4096)));
volatile unsigned k70_formal_boot_map_status;
/* Exception entry cannot rely on a live C function preserving x20's value. */
volatile uintptr_t k70_formal_boot_args_pa;
extern char ExceptionVectorsBase[];
unsigned k70_formal_bootstrap(const boot_args *, volatile uint64_t *);
void k70_formal_trap(uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,const boot_args *);
void k70_formal_c_entry(void *);

/* Runs on a physical, dedicated stack with MMU off, after XNU's tables exist.
 * No allocator, UEFI service, device register, or pointer initialized at link time. */
__attribute__((no_stack_protector))
unsigned k70_formal_bootstrap(const boot_args *args, volatile uint64_t *root)
{
    if (args->Video.v_baseAddr!=UINT64_C(0xb8000000) || args->Video.v_width!=1440 ||
        args->Video.v_height!=3200 || args->Video.v_rowBytes!=5760 ||
        (args->Video.v_depth & 255)!=32 || args->physBase>UINT64_MAX-args->memSize) {
        return 0;
    }
    k70_formal_boot_map_status=k70_bootstrap_fb_map(root,k70_formal_fb_l2,
        args->physBase,args->physBase+args->memSize);
    return k70_formal_boot_map_status;
}

/* Source-level low-vector trap. The ASM wrapper supplies a dedicated stack and
 * captures registers before C. Fatal only: it never returns to a failed path. */
__attribute__((no_stack_protector))
void k70_formal_trap(uint64_t esr, uint64_t elr, uint64_t far, uint64_t sctlr,
    uint64_t tcr, uint64_t ttbr0, uint64_t ttbr1, const boot_args *args)
{
    static volatile unsigned entered;
    if (entered) { return; }
    entered=1;
    if (!bp_translated((uintptr_t)args) || !bp_translated((uintptr_t)args+87)) { return; }
    if (args->Video.v_baseAddr!=UINT64_C(0xb8000000)) { return; }
    /* Fatal entry must bypass the normal observer lock; the interrupted code
     * will never resume. Geometry and all WRITE translations are still checked. */
    bp_impl_init();
    bp_impl_bind((uintptr_t)args->Video.v_baseAddr,(unsigned)args->Video.v_width,
        (unsigned)args->Video.v_height,(unsigned)args->Video.v_rowBytes,
        (unsigned)args->Video.v_depth & 255);
    if (!g_screen.bound) { return; }
    bp_model_row(0,"K70 FORMAL XNU - EARLY EXCEPTION",BP_WHITE,BP_RED);
    const uint64_t values[]={esr,elr,far,sctlr,tcr,ttbr0,ttbr1};
    /* Avoid static pointer tables: the same code must also run at its PA. */
    for (unsigned i=0;i<7;i++) {
        char line[BP_MAX_COLS+1]; struct bp_out out;
        bp_out_begin(&out,line);
        switch(i) {
        case 0: bp_out_puts(&out,"ESR_EL1   "); break;
        case 1: bp_out_puts(&out,"ELR_EL1   "); break;
        case 2: bp_out_puts(&out,"FAR_EL1   "); break;
        case 3: bp_out_puts(&out,"SCTLR_EL1 "); break;
        case 4: bp_out_puts(&out,"TCR_EL1   "); break;
        case 5: bp_out_puts(&out,"TTBR0_EL1 "); break;
        default: bp_out_puts(&out,"TTBR1_EL1 "); break;
        }
        bp_out_hex(&out,values[i],16);
        bp_model_row(i+2,line,BP_WHITE,BP_BLACK);
    }
    bp_model_row(10,"Stopped in early XNU; no automatic retry",BP_AMBER,BP_BLACK);
    bp_flush();
}

void k70_formal_c_entry(void *opaque)
{
    const boot_args *args=opaque;
    boot_progress_init();
    if (args->Video.v_baseAddr!=UINT64_C(0xb8000000)) { return; }
    boot_progress_bind((uintptr_t)args->Video.v_baseAddr,(unsigned)args->Video.v_width,
        (unsigned)args->Video.v_height,(unsigned)args->Video.v_rowBytes,
        (unsigned)args->Video.v_depth & 255);
    boot_progress_stage("arm_init entered; bootstrap framebuffer validated if visible");
    boot_progress_stage(k70_formal_boot_map_status ?
        "bootstrap framebuffer identity mapping installed" : "bootstrap framebuffer mapping refused");
}

static uint64_t k70_fb_pa;
static unsigned k70_fb_width, k70_fb_height, k70_fb_stride, k70_fb_depth;
static uintptr_t k70_fb_va;
void k70_formal_early(void *opaque);
static const char *k70_cpu_first_refusal;
static uint64_t k70_cpu_refusal_value;

/* Written from XNU's C sources and read by the timer thread. This file is
 * included into a C++ translation unit, so the definitions need C linkage or
 * the injected extern declarations resolve to a different symbol and every
 * stage mark silently disappears. */
#ifdef __cplusplus
extern "C" {
#endif
volatile uint32_t k70_window_reads;
volatile uint64_t k70_window_last_daif;
volatile uint32_t k70_stage_mark;
extern volatile uint32_t k70_pid1_ran;
extern volatile uint32_t k70_f0, k70_f2, k70_f3, k70_f5;
extern volatile int32_t k70_f1;
extern volatile uint32_t k70_b_iter;
extern volatile int32_t k70_b_wr, k70_b_br;
extern volatile uint32_t k70_p6, k70_p7, k70_p8, k70_bsd;
extern volatile uint32_t k70_stage, k70_exec_errno;
extern unsigned int startup_phase;
boolean_t preemption_enabled(void);
int get_preemption_level(void);
extern volatile uint32_t k70_faults, k70_fault_kr;
extern volatile uint32_t k70_tt_fail, k70_tt_pre;
extern volatile uint64_t k70_pv, k70_pmin, k70_pmax;
extern volatile uint64_t k70_va_bits, k70_va_max;
extern volatile uint32_t k70_fix_count;
extern volatile uint64_t k70_ptte;
extern volatile uint32_t k70_free_pages;
extern volatile uint32_t k70_pv_loops, k70_pv_status, k70_pv_count;
extern volatile uint32_t k70_plevel, k70_proot, k70_pdump;
#ifdef __cplusplus
}
#endif

/* Called by the formal ArmCpu BUILD COPY. Uses the existing nonblocking
 * renderer; no MMIO, allocation, sleeping, or scheduler policy changes. */
void k70_formal_cpu_trace(const char *stage, uint64_t value)
{
    /* Every trace repaints the console, and one SCSI command can emit a dozen
     * of them. Once the boot starts reading the root volume that flood starves
     * the machine: the timer thread stops ticking and the board resets. The
     * first commands stay fully visible, the rest are sampled. */
    static unsigned k70_trace_calls;
    /* Only the transport floods: one disk command emits a dozen lines and a
     * boot reads thousands of commands. Everything else prints in full, so the
     * PID 1 boundary lines cannot be sampled away. */
    if (stage[0] == 'U' && stage[1] == 'F' && stage[2] == 'S') {
        unsigned call = ++k70_trace_calls;
        if (call > 120 && (call & 63u)) {
            k70_window_reads++;
            return;
        }
        k70_window_reads++;
        uint64_t daif;
        __asm__ volatile ("mrs %0, daif" : "=r" (daif));
        k70_window_last_daif = daif;
    }
    if (stage[0] == 'F' && !k70_cpu_first_refusal) {
        k70_cpu_first_refusal = stage;
        k70_cpu_refusal_value = value;
    }
    char line[BP_MAX_COLS + 1];
    struct bp_out out;
    bp_out_begin(&out, line);
    bp_out_puts(&out, "CPU: ");
    bp_out_puts(&out, stage);
    bp_out_puts(&out, " value=0x");
    bp_out_hex(&out, value, 16);
    boot_progress_stage(line);
}
void k70_formal_after_vm(void);
void k70_formal_thread_start(void);
extern volatile uint32_t armcpu_gic_ready;
extern volatile uint64_t armcpu_timer_interrupts;
extern volatile uint32_t armcpu_registered;
extern volatile uint32_t armcpu_gic_boot[8];
extern volatile uint32_t armdt_platform_configured, armdt_platform_cpu_count;
extern volatile uint32_t armcpu_gic_stride, armcpu_gic_typer_probe[2];
volatile uint64_t k70_formal_thread_turn;
static volatile unsigned k70_worker_started;
static volatile unsigned k70_cpu_online_ready;

static int k70_formal_claim_worker(void)
{
    if (!__atomic_load_n(&k70_cpu_online_ready, __ATOMIC_ACQUIRE) ||
        !armcpu_registered || !armcpu_gic_ready) { return 0; }
    unsigned expected = 0;
    return __atomic_compare_exchange_n(&k70_worker_started, &expected, 1, 0,
        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
}

/* Late snapshot before root-device waiting, after asynchronous matching has
 * had another opportunity to run. Reads existing RAM counters only. */
void k70_formal_cpu_summary(void)
{
    k70_stage_mark = k70_stage_mark ? k70_stage_mark : 100;  /* adapter can write it */
    k70_formal_cpu_trace("late platform configured", armdt_platform_configured);
    k70_formal_cpu_trace("late CPU nubs", armdt_platform_cpu_count);
    k70_formal_cpu_trace("late CPU registered", armcpu_registered);
    k70_formal_cpu_trace("late GIC ready", armcpu_gic_ready);
    k70_formal_cpu_trace("late timer interrupts", armcpu_timer_interrupts);
    k70_formal_cpu_trace("late GIC stride", armcpu_gic_stride);
    k70_formal_cpu_trace("late redistributor offset", armcpu_gic_typer_probe[0]);
    k70_formal_cpu_trace("late redistributor TYPER low", armcpu_gic_typer_probe[1]);
    k70_formal_cpu_trace(k70_cpu_first_refusal ? k70_cpu_first_refusal :
        "no CPU refusal captured", k70_cpu_refusal_value);
    boot_progress_stage("root-device lookup next; no system root configured in this candidate");
}

static void k70_formal_worker(void *argument, wait_result_t result)
{
    (void)argument;
    (void)result;
    for (;;) {
        char line[BP_MAX_COLS + 1];
        struct bp_out out;
        bp_out_begin(&out, line);
        k70_formal_thread_turn++;
        if (k70_formal_thread_turn >= 2) { k70_formal_milestones |= 8; }
        if (armcpu_timer_interrupts) { k70_formal_milestones |= 16; }
        /* One line per second, fixed width, no per-command output. It answers
         * the only question a reset leaves open: were timer interrupts still
         * arriving, and how far had the boot got. */
        bp_out_puts(&out, "S");
        bp_out_dec(&out, k70_stage_mark);
        bp_out_puts(&out, " T");
        bp_out_dec(&out, (uint32_t)armcpu_timer_interrupts);
        bp_out_puts(&out, " H");
        bp_out_dec(&out, (uint32_t)k70_formal_thread_turn);
        bp_out_puts(&out, " U");
        bp_out_dec(&out, (uint32_t)k70_window_reads);
        bp_out_puts(&out, " G");
        bp_out_dec(&out, (uint32_t)k70_stage);
        bp_out_puts(&out, " S");
        bp_out_dec(&out, (uint32_t)startup_phase);
        bp_out_puts(&out, "/");
        bp_out_dec(&out, (uint32_t)preemption_enabled());
        bp_out_puts(&out, "/");
        bp_out_dec(&out, (uint32_t)get_preemption_level());
        bp_out_puts(&out, " T");
        bp_out_dec(&out, (uint32_t)k70_tt_fail);
        bp_out_dec(&out, (uint32_t)k70_fix_count);
        if (k70_tt_fail != 0) {
            void k70_formal_cpu_trace(const char *, uint64_t);
            switch ((unsigned)(k70_formal_thread_turn % 9u)) {
            case 0u: k70_formal_cpu_trace("Z1 pmap v", k70_pv); break;
            case 1u: k70_formal_cpu_trace("Z2 pmap min", k70_pmin); break;
            case 2u: k70_formal_cpu_trace("Z3 pmap max", k70_pmax); break;
            case 3u: k70_formal_cpu_trace("Z4 levels leaf/root",
                         ((uint64_t)k70_plevel << 8) | (uint64_t)k70_proot); break;
            case 4u: k70_formal_cpu_trace("Z5 tt attempts", (uint64_t)k70_tt_fail); break;
            case 5u: k70_formal_cpu_trace("Z6 va bits/max",
                         (k70_va_bits << 56) | (k70_va_max >> 8)); break;
            case 6u: k70_formal_cpu_trace("Z7 pmap root tte", k70_ptte); break;
            case 7u: k70_formal_cpu_trace("Z8 free pages", (uint64_t)k70_free_pages); break;
            default: k70_formal_cpu_trace("Z9 pv loops/status/count",
                         ((uint64_t)k70_pv_loops << 40) | ((uint64_t)k70_pv_status << 20) | (uint64_t)k70_pv_count); break;
            }
        }
        bp_out_puts(&out, " D");
        bp_out_hex(&out, k70_window_last_daif, 2);
        boot_progress_stage(line);
        /* Each subsequent turn requires a scheduler wakeup after one second.
         * Unlike a busy counter loop this can establish continued scheduling. */
        uint64_t deadline;
        clock_interval_to_deadline(1, NSEC_PER_SEC, &deadline);
        (void)assert_wait_deadline((event_t)&k70_formal_thread_turn, THREAD_UNINT, deadline);
        thread_block(THREAD_CONTINUE_NULL);
    }
}

void k70_formal_thread_start(void)
{
    char line[BP_MAX_COLS + 1];
    struct bp_out out;
    bp_out_begin(&out, line);
    bp_out_puts(&out, "NATIVE CPU registered=");
    bp_out_dec(&out, armcpu_registered);
    bp_out_puts(&out, " GIC=");
    bp_out_dec(&out, armcpu_gic_ready);
    boot_progress_stage(line);
    for (unsigned i = 0; i < 8; i++) {
        bp_out_begin(&out, line);
        bp_out_puts(&out, "GIC boot snapshot[");
        bp_out_dec(&out, i);
        bp_out_puts(&out, "]=0x");
        bp_out_hex(&out, armcpu_gic_boot[i], 8);
        boot_progress_stage(line);
    }
    if (!armcpu_gic_ready) {
        boot_progress_stage("diagnostic thread deferred until boot CPU is online");
        return;
    }
    if (!k70_formal_claim_worker()) { return; }
    thread_t worker = THREAD_NULL;
    kern_return_t status = kernel_thread_start(k70_formal_worker, 0, &worker);
    if (status == KERN_SUCCESS) {
        thread_deallocate(worker);
        boot_progress_stage("diagnostic thread created; wakeups not yet verified");
    } else {
        boot_progress_stage("diagnostic thread creation failed");
    }
}

/* Invoked once the real boot CPU start path has completed IRQ/timer setup.
 * The early screen hook may run first; the atomic claim permits one worker. */
void k70_formal_cpu_online(void)
{
    __atomic_store_n(&k70_cpu_online_ready, 1, __ATOMIC_RELEASE);
    k70_formal_thread_start();
}

void k70_formal_early(void *opaque)
{
    /* Native vectors take over once the initial C observer is available. */
    __asm__ volatile ("msr vbar_el1, %0\n\tisb" :: "r"(ExceptionVectorsBase) : "memory");
    k70_formal_milestones |= 1; /* PE_init_platform(FALSE) returned. */
    const boot_args *args = opaque;
    k70_fb_pa = args->Video.v_baseAddr;
    k70_fb_width = (unsigned)args->Video.v_width;
    k70_fb_height = (unsigned)args->Video.v_height;
    k70_fb_stride = (unsigned)args->Video.v_rowBytes;
    k70_fb_depth = (unsigned)args->Video.v_depth & 0xff;
    boot_progress_init();
    if (k70_fb_pa != UINT64_C(0xb8000000)) { return; }
    boot_progress_bind((uintptr_t)k70_fb_pa, k70_fb_width, k70_fb_height,
                       k70_fb_stride, k70_fb_depth);
    boot_progress_stage("PE_init_platform(FALSE) returned; native XNU C");
}

void k70_formal_after_vm(void)
{
    k70_formal_milestones |= 2; /* arm_vm_init returned, even if binding fails. */
    if (k70_fb_pa != UINT64_C(0xb8000000) || k70_fb_width != 1440 ||
        k70_fb_height != 3200 || k70_fb_stride != 5760 || k70_fb_depth != 32) {
        return;
    }
    /* Create a kernel-owned mapping, rather than guessing physmap arithmetic.
     * This routine is reached only after arm_vm_init has returned. */
    k70_fb_va = ml_io_map_wcomb(k70_fb_pa, (uint64_t)k70_fb_stride * k70_fb_height);
    boot_progress_bind(k70_fb_va, k70_fb_width, k70_fb_height,
                       k70_fb_stride, k70_fb_depth);
    if (boot_progress_active()) { k70_formal_milestones |= 4; }
    boot_progress_stage(boot_progress_active() ?
        "kernel framebuffer mapping validated after arm_vm_init" :
        "kernel framebuffer mapping unavailable after arm_vm_init");
    uint64_t ttbr0, ttbr1, sctlr;
    __asm__ volatile ("mrs %0, ttbr0_el1\n\tmrs %1, ttbr1_el1\n\tmrs %2, sctlr_el1"
                      : "=r"(ttbr0), "=r"(ttbr1), "=r"(sctlr));
    char line[BP_MAX_COLS + 1];
    struct bp_out out;
    bp_out_begin(&out, line);
    bp_out_puts(&out, "VM TTBR0="); bp_out_hex(&out, ttbr0, 16);
    bp_out_puts(&out, " TTBR1="); bp_out_hex(&out, ttbr1, 16);
    boot_progress_stage(line);
    bp_out_begin(&out, line);
    bp_out_puts(&out, "VM SCTLR="); bp_out_hex(&out, sctlr, 16);
    boot_progress_stage(line);
}
