/* SPDX-License-Identifier: MIT */
#ifndef K70_COPYOUT_DIAGNOSTICS_H
#define K70_COPYOUT_DIAGNOSTICS_H

/* Shared with the ARM64 copy leaf. Zero means no observed call. */
#define K70_COPY_ARMED          1
#define K70_COPY_VALIDATING     2
#define K70_COPY_VALIDATED      3
#define K70_COPY_DISPATCH       4
#define K70_COPY_ACCESS         5
#define K70_COPY_LEAF_RETURNED  6
#define K70_COPY_KERNEL         7
#define K70_COPY_EMPTY          8

#ifndef __ASSEMBLER__
#include <stdint.h>

enum {
    K70_COPY_SYNC = 1,
    K70_COPY_ABORT,
    K70_COPY_FAST_FAULT,
    K70_COPY_FAST_RETURNED,
    K70_COPY_VM_FAULT,
    K70_COPY_VM_RETURNED,
    K70_COPY_RECOVER,
};

extern volatile uintptr_t k70_copyout_thread;
extern volatile uint32_t k70_copyout_phase, k70_copyout_abort_phase;
extern volatile uint32_t k70_copyout_abort_count;
extern volatile int32_t k70_copyout_validate_rc, k70_copyout_fault_rc;
extern volatile uint32_t k70_copyout_first_esr, k70_copyout_first_phase;
extern volatile uint64_t k70_copyout_first_far, k70_copyout_first_pc;
extern volatile uint64_t k70_copyout_dst, k70_copyout_size;

enum {
    K70_COPY_FAST_REF_MOD = 1,
    K70_COPY_FAST_ALREADY_WRITABLE,
    K70_COPY_FAST_TARGETED,
};

struct k70_copyout_vm_sample {
    uint64_t pc, ttbr0, tcr, sctlr, mmfr1;
    uint64_t map_ttbr0, pte_before, pte_after;
    uint64_t par_el1w, par_el0w;
    uint32_t spsr, table_ap, reason, pte_valid, fast_rc;
};

extern volatile struct k70_copyout_vm_sample k70_copyout_vm[2];
extern volatile uint32_t k70_copyout_vm_active, k70_copyout_vm_done;

static inline int
k70_copyout_owned(uintptr_t thread)
{
    uintptr_t owner = k70_copyout_thread;
    return owner != 0 && owner == thread;
}

/* The first sample is observational. Issue AT only after a matching fault has
 * already recurred after success, so AT cannot affect the initial retry. */
static inline void
k70_copyout_vm_begin(uint64_t far, uint64_t pc, uint32_t spsr)
{
    uint32_t done = __atomic_load_n(&k70_copyout_vm_done, __ATOMIC_ACQUIRE);
    if (k70_copyout_phase != K70_COPY_ACCESS || far != k70_copyout_dst ||
        k70_copyout_vm_active || done >= 2 ||
        (done == 1 && (k70_copyout_vm[0].fast_rc != 0 || k70_copyout_vm[0].pc != pc))) {
        return;
    }

    volatile struct k70_copyout_vm_sample *sample = &k70_copyout_vm[done];
    uint64_t ttbr0, tcr, sctlr, mmfr1;
    __asm__ volatile("mrs %0, ttbr0_el1\n\t"
        "mrs %1, tcr_el1\n\t"
        "mrs %2, sctlr_el1\n\t"
        "mrs %3, id_aa64mmfr1_el1"
        : "=r"(ttbr0), "=r"(tcr), "=r"(sctlr), "=r"(mmfr1) :: "memory");
    sample->pc = pc;
    sample->spsr = spsr;
    sample->ttbr0 = ttbr0;
    sample->tcr = tcr;
    sample->sctlr = sctlr;
    sample->mmfr1 = mmfr1;
    k70_copyout_vm_active = done + 1;

    if (done == 1) {
        uint64_t daif, saved_par, par_el1w, par_el0w;
        __asm__ volatile("mrs %0, daif\n\tmsr daifset, #15\n\t"
            "mrs %1, par_el1\n\tat s1e1w, %4\n\tisb\n\tmrs %2, par_el1\n\t"
            "at s1e0w, %4\n\tisb\n\tmrs %3, par_el1\n\t"
            "msr par_el1, %1\n\tmsr daif, %0"
            : "=&r"(daif), "=&r"(saved_par), "=&r"(par_el1w), "=&r"(par_el0w)
            : "r"(far) : "memory");
        sample->par_el1w = par_el1w;
        sample->par_el0w = par_el0w;
    }
}

static inline void
k70_copyout_vm_end(uint64_t far, uint64_t pc, uint32_t rc)
{
    uint32_t active = k70_copyout_vm_active;
    if (active >= 1 && active <= 2 && far == k70_copyout_dst &&
        k70_copyout_vm[active - 1].pc == pc) {
        k70_copyout_vm[active - 1].fast_rc = rc;
        k70_copyout_vm_active = 0;
        __atomic_store_n(&k70_copyout_vm_done, active, __ATOMIC_RELEASE);
    }
}

static inline void
k70_copyout_sync(uint32_t esr, uint64_t far, uint64_t pc)
{
    uint32_t count = __atomic_load_n(&k70_copyout_abort_count, __ATOMIC_RELAXED);
    if (count == 0) {
        k70_copyout_first_esr = esr;
        k70_copyout_first_far = far;
        k70_copyout_first_pc = pc;
        k70_copyout_first_phase = k70_copyout_phase;
    }
    k70_copyout_abort_phase = K70_COPY_SYNC;
    if (count != UINT32_MAX) {
        __atomic_store_n(&k70_copyout_abort_count, count + 1, __ATOMIC_RELEASE);
    }
}
#endif
#endif
