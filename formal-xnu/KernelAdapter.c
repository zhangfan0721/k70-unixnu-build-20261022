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

static uint64_t k70_fb_pa;
static unsigned k70_fb_width, k70_fb_height, k70_fb_stride, k70_fb_depth;
static uintptr_t k70_fb_va;
void k70_formal_early(void *opaque);
void k70_formal_after_vm(void);
void k70_formal_thread_start(void);
extern volatile uint32_t armcpu_gic_ready;
extern volatile uint64_t armcpu_timer_interrupts;
extern volatile uint32_t armcpu_registered;
extern volatile uint32_t armcpu_gic_boot[8];
volatile uint64_t k70_formal_thread_turn;

static void k70_formal_worker(void *argument, wait_result_t result)
{
    (void)argument;
    (void)result;
    for (;;) {
        char line[BP_MAX_COLS + 1];
        struct bp_out out;
        bp_out_begin(&out, line);
        bp_out_puts(&out, "THREAD turn=");
        bp_out_dec(&out, ++k70_formal_thread_turn);
        bp_out_puts(&out, " GIC=");
        bp_out_dec(&out, armcpu_gic_ready);
        bp_out_puts(&out, " TIMER=");
        bp_out_dec(&out, armcpu_timer_interrupts);
        if (k70_formal_thread_turn >= 2) { k70_formal_milestones |= 8; }
        if (armcpu_timer_interrupts) { k70_formal_milestones |= 16; }
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
        boot_progress_stage("diagnostic thread not started: native GIC is not ready");
        return;
    }
    thread_t worker = THREAD_NULL;
    kern_return_t status = kernel_thread_start(k70_formal_worker, 0, &worker);
    if (status == KERN_SUCCESS) {
        thread_deallocate(worker);
        boot_progress_stage("diagnostic thread created; wakeups not yet verified");
    } else {
        boot_progress_stage("diagnostic thread creation failed");
    }
}

void k70_formal_early(void *opaque)
{
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
    __asm__ volatile ("mrs %0, ttbr0_el1; mrs %1, ttbr1_el1; mrs %2, sctlr_el1"
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
