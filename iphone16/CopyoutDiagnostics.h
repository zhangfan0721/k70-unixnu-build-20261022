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

static inline int
k70_copyout_owned(uintptr_t thread)
{
    uintptr_t owner = k70_copyout_thread;
    return owner != 0 && owner == thread;
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
