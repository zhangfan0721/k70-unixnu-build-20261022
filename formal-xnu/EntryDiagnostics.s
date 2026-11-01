// SPDX-License-Identifier: BSD-2-Clause-Patent
// Included by start.s; only x9..x15 and NZCV are scratch in K70_MARK.
// Offsets are statically checked against the actual ARM64 boot_args in C.
.macro K70_MARK args, colour, band
    ldr x9, [\args, #40]
    mov x10, #0xb8000000
    cmp x9, x10
    b.ne Lk70_skip\@
    ldr x10, [\args, #56]
    mov x11, #5760
    cmp x10, x11
    b.ne Lk70_skip\@
    ldr x10, [\args, #64]
    cmp x10, #1440
    b.ne Lk70_skip\@
    ldr x10, [\args, #72]
    cmp x10, #3200
    b.ne Lk70_skip\@
    ldr x10, [\args, #80]
    and x10, x10, #255
    cmp x10, #32
    b.ne Lk70_skip\@
    // Repaint the loader-sized top 200 rows, beyond the curved bezel.
    // band remains a callsite ID; all stages use this same bounded area.
    mov x10, #0x9400
    movk x10, #0x11, lsl #16   // 5760 * 200 = 1152000 bytes
    // After the MMU is on, a refused map must not turn a marker into a fault.
    // Validate every touched page as writable and identity-mapped; restore PAR.
    mrs x13, SCTLR_EL1
    tbz x13, #0, Lk70_valid\@
    mrs x15, PAR_EL1
    mov x13, x9
    add x14, x9, x10
Lk70_probe\@:
    at s1e1w, x13
    isb
    mrs x11, PAR_EL1
    tbnz x11, #0, Lk70_probe_failed\@
    and x11, x11, #0x000ffffffffff000
    and x12, x13, #0xfffffffffffff000
    cmp x11, x12
    b.ne Lk70_probe_failed\@
    add x13, x12, #4096
    cmp x13, x14
    b.lo Lk70_probe\@
    msr PAR_EL1, x15
    b Lk70_valid\@
Lk70_probe_failed\@:
    msr PAR_EL1, x15
    b Lk70_skip\@
Lk70_valid\@:
    mov w12, #(\colour & 0xffff)
    movk w12, #((\colour >> 16) & 0xffff), lsl #16
Lk70_paint\@:
    stp w12, w12, [x9], #8
    subs x10, x10, #8
    b.ne Lk70_paint\@
    dsb sy
Lk70_skip\@:
.endmacro

// Inline the call wrapper: preserve the original arm_init LR, not a BL return.
.macro K70_PREPARE_DISPLAY
    // Original SP is a future KVA. Use a physical stack for the MMU-off C call.
    // AAPCS preserves x19/x27/x28 across that call.
    mov x27, sp
    mov x28, lr
    adrp x9, EXT(k70_formal_fault_stack)@page
    add x9, x9, EXT(k70_formal_fault_stack)@pageoff
    add x9, x9, #4, lsl #12
    mov sp, x9
    mrs x19, CPACR_EL1
    orr x9, x19, #(3 << 20)
    msr CPACR_EL1, x9
    isb
    mov x0, x20
    mov x1, x25
    bl EXT(k70_formal_bootstrap)
    msr CPACR_EL1, x19
    isb
    mov sp, x27
    mov lr, x28
.endmacro

// Emit helpers after the original start code so reset-vector layout stays intact.
.macro K70_ENTRY_HELPERS
    .text
    .align 2
    .globl EXT(k70_formal_early_exception)
LEXT(k70_formal_early_exception)
    msr DAIFSet, #15
    adrp x9, EXT(k70_formal_fault_stack)@page
    add x9, x9, EXT(k70_formal_fault_stack)@pageoff
    add x9, x9, #4, lsl #12
    mov sp, x9
    mrs x9, CPACR_EL1
    orr x9, x9, #(3 << 20)
    msr CPACR_EL1, x9
    isb
    mrs x0, ESR_EL1
    mrs x1, ELR_EL1
    mrs x2, FAR_EL1
    mrs x3, SCTLR_EL1
    mrs x4, TCR_EL1
    mrs x5, TTBR0_EL1
    mrs x6, TTBR1_EL1
    adrp x9, EXT(k70_formal_boot_args_pa)@page
    add x9, x9, EXT(k70_formal_boot_args_pa)@pageoff
    ldr x7, [x9]
    bl EXT(k70_formal_trap)
Lk70_fault_park:
    wfe
    b Lk70_fault_park
    .comm EXT(k70_formal_fault_stack),16384,4
.endmacro
