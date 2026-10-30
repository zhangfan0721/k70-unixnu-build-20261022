// Owned, identity-mapped transition. No stack, external references or return.
.text
.macro constant reg, value
 movz \reg, #(\value & 0xffff)
 movk \reg, #((\value >> 16) & 0xffff), lsl #16
 movk \reg, #((\value >> 32) & 0xffff), lsl #32
 movk \reg, #((\value >> 48) & 0xffff), lsl #48
.endm
.macro equal reg, value
 constant x11, \value
 cmp \reg, x11
 b.ne transition_bad
.endm
.global transition_begin
.global transition_mask_interrupts
.global transition_clean_loop
.global transition_halt
transition_begin:
 equal x0, 0x881548000
 equal x1, 0x8803f9488
 equal x2, 0x880004000
 equal x3, 0x10000000
 equal x4, 0xb8000000
 equal x5, 0x1194000
 adr x9, transition_begin
 equal x9, 0x881604000
 mrs x9, CurrentEL
 equal x9, 4
transition_mask_interrupts:
 msr daifset, #15
 // Purple confirms that the copied transition itself executed after EBS.
 mov x9, x4
 constant x10, 0xffa000ff
 constant x11, 92160
1: str w10, [x9], #4
 subs x11, x11, #1
 b.ne 1b
 mrs x7, ctr_el0
 ubfx x7, x7, #16, #4
 mov x9, #4
 lsl x7, x9, x7
 cmp x7, #16
 b.lo transition_bad
 cmp x7, #4096
 b.hi transition_bad
 sub x9, x7, #1
 tst x2, x9
 b.ne transition_bad
 tst x3, x9
 b.ne transition_bad
 sub x6, x2, #4, lsl #12 // Include the separately owned16KiB prefix guard.
 add x8, x2, x3
transition_clean_loop:
 dc civac, x6
 add x6, x6, x7
 cmp x6, x8
 b.lo transition_clean_loop
 dsb sy
 ic iallu
 dsb sy
 isb
 mrs x9, sctlr_el1
 constant x10, 0x1005
 bic x9, x9, x10
 msr sctlr_el1, x9
 isb
 tlbi vmalle1
 dsb sy
 isb
 // Orange confirms that instructions and MMIO writes continued with M/C/I off.
 constant x9, 0xb805a000 // row 64
 constant x10, 0xffffa000
 constant x11, 92160
2: str w10, [x9], #4
 subs x11, x11, #1
 b.ne 2b
 dsb sy
 // Capture even an exception on the very first original CPU instruction.
 constant x9, 0x8803fa000
 msr vbar_el1, x9
 isb
 b gic_setup
setup_complete:
 br x1
transition_bad:
 constant x9, 0xb8000000
 constant x10, 0xffff0000
 constant x11, 184320
3: str w10, [x9], #4
 subs x11, x11, #1
 b.ne 3b
 dsb sy
transition_halt:
 wfe
 b transition_halt


// Only the existing M0 transition accesses GIC MMIO. x0..x5 remain intact.
.macro poll reg, offset, bit, failure
 mov x17, #1
 lsl x17, x17, #16
91: ldr w9, [\reg, #\offset]
 tbz w9, #\bit, 92f
 subs x17, x17, #1
 b.ne 91b
 b \failure
92:
.endm
.global gic_setup
gic_setup:
 constant x19, 0x881606000
 constant x20, 0x17100000
 ldr w9, [x20]
 str x9, [x19, #512]
 and w10, w9, #7
 cbnz w10, gic_bad
 tbz w9, #4, gic_bad
 poll x20, 0, 31, gic_bad
 mrs x9, ICC_SRE_EL1
 tbz x9, #0, gic_bad
 mrs x9, ICC_CTLR_EL1
 str x9, [x19, #664]
 tbnz x9, #1, gic_bad
 mrs x9, ICC_IGRPEN1_EL1
 str x9, [x19, #536]
 tbnz x9, #0, gic_bad
 mrs x9, ICC_RPR_EL1
 and x9, x9, #255
 cmp x9, #255
 b.ne gic_bad
 mrs x9, cntv_ctl_el0
 and x9, x9, #3
 str x9, [x19, #552]
 tbnz x9, #0, gic_bad
 mrs x9, cntv_cval_el0
 str x9, [x19, #560]
 mrs x9, mpidr_el1
 and x22, x9, #0xffffff
 ubfx x23, x9, #32, #8
 orr x22, x22, x23, lsl #24
 constant x21, 0x17180000
 constant x23, 0x17380000
 mov x24, #16
gic_scan:
 add x9, x21, #0x20000
 cmp x9, x23
 b.hi gic_bad
 ldr x9, [x21, #8]
 lsr x10, x9, #32
 cmp x10, x22
 b.eq gic_found
 tbnz x9, #4, gic_bad
 mov x10, #0x20000
 tbz x9, #1, 1f
 lsl x10, x10, #1
1: add x21, x21, x10
 subs x24, x24, #1
 b.ne gic_scan
 b gic_bad
gic_found:
 str x21, [x19, #528]
 str x9, [x19, #576]
 add x25, x21, #0x10000
 constant x10, 0xffe8
 ldr w9, [x21, x10]
 str x9, [x19, #616]
 ubfx w9, w9, #4, #4
 cmp w9, #3
 b.eq 2f
 cmp w9, #4
 b.ne gic_bad
2: poll x21, 0, 3, gic_bad
 ldr w9, [x21]
 tbnz w9, #0, gic_bad
 ldr w9, [x21, #0x14]
 str x9, [x19, #592]
 tst w9, #6
 b.ne gic_bad
 ldr w9, [x25, #0x100]
 str x9, [x19, #680]
 cbnz w9, gic_bad
 ldr w9, [x25, #0x300]
 str x9, [x19, #688]
 cbnz w9, gic_bad
 ldr w9, [x25, #0x80]
 str x9, [x19, #584]
 tbz w9, #27, gic_bad
 ldr w9, [x25, #0xc04]
 str x9, [x19, #600]
 tbnz w9, #23, gic_bad
 ldr w9, [x25, #0x418]
 lsr w9, w9, #24
 str x9, [x19, #568]
 mrs x10, ICC_PMR_EL1
 str x10, [x19, #608]
 and w10, w10, #255
 cmp w10, w9
 b.ls gic_bad
 ldr w26, [x20, #4]
 str x26, [x19, #624]
 and w10, w26, #31
 add w10, w10, #1
 lsl w10, w10, #2
 mov x11, #4
 add x27, x20, #0x100
3: ldr w9, [x27, x11]
 cbnz w9, gic_bad
 add x11, x11, #4
 cmp x11, x10
 b.lo 3b
 tbz w26, #8, gic_mutate
 ubfx w10, w26, #27, #5
 add w10, w10, #1
 lsl w10, w10, #2
 mov x11, #0
 add x27, x20, #0x1000
 add x27, x27, #0x200
4: ldr w9, [x27, x11]
 cbnz w9, gic_bad
 add x11, x11, #4
 cmp x11, x10
 b.lo 4b
gic_mutate:
 mov x9, #1
 str x9, [x19, #632]
 mov x9, #2
 msr cntv_ctl_el0, x9
 isb
 mov w28, #0x8000000
 str w28, [x25, #0x280]
 ldr w9, [x19, #512]
 orr w9, w9, #2
 str x9, [x19, #520]
 str w9, [x20]
 dsb sy
 poll x20, 0, 31, gic_bad
 ldr w9, [x20]
 ldr w10, [x19, #520]
 cmp w9, w10
 b.ne gic_bad
 str w28, [x25, #0x100]
 dsb sy
 poll x21, 0, 3, gic_bad
 ldr w9, [x25, #0x100]
 cmp w9, w28
 b.ne gic_bad
 mov x9, #1
 msr ICC_IGRPEN1_EL1, x9
 isb
 mrs x9, ICC_IGRPEN1_EL1
 str x9, [x19, #544]
 cmp x9, #1
 b.ne gic_bad
 str x9, [x19, #640]
 b setup_complete
gic_bad:
 mov x10, #2
 mov x12, #40
 constant x9, CAPTURE_PA
 br x9

.org 0x700
.global gic_restore
gic_restore:
 msr daifset, #15
 constant x19, 0x881606000
 ldr x9, [x19, #632]
 cbz x9, restore_paint
 mov x9, #2
 msr cntv_ctl_el0, x9
 msr ICC_IGRPEN1_EL1, xzr
 isb
 ldr x9, [x19, #560]
 msr cntv_cval_el0, x9
 ldr x9, [x19, #552]
 msr cntv_ctl_el0, x9
 isb
 mrs x10, cntv_cval_el0
 ldr x11, [x19, #560]
 cmp x10, x11
 b.ne restore_bad
 str x10, [x19, #1232]
 mrs x10, cntv_ctl_el0
 and x10, x10, #3
 cmp x10, x9
 b.ne restore_bad
 str x10, [x19, #1240]
 constant x20, 0x17100000
 ldr x21, [x19, #528]
 add x25, x21, #0x10000
 mov w28, #0x8000000
 str w28, [x25, #0x180]
 str w28, [x25, #0x280]
 dsb sy
 poll x21, 0, 3, restore_bad
 ldr w9, [x25, #0x100]
 cbnz w9, restore_bad
 ldr w9, [x25, #0x300]
 cbnz w9, restore_bad
 ldr w9, [x19, #512]
 str w9, [x20]
 dsb sy
 poll x20, 0, 31, restore_bad
 ldr w9, [x20]
 str x9, [x19, #240]
 ldr w10, [x19, #512]
 cmp w9, w10
 b.ne restore_bad
 ldr x9, [x19, #536]
 msr ICC_IGRPEN1_EL1, x9
 isb
 mrs x10, ICC_IGRPEN1_EL1
 str x10, [x19, #264]
 cmp x9, x10
 b.ne restore_bad
 mov x9, #1
 str x9, [x19, #648]
 str x9, [x19, #272]
 ldr x10, [x19, #1200]
 cmp x10, #1
 b.ne restore_paint
 ldr x10, [x19, #8]
 cmp x10, #2
 b.ne restore_paint
 ldr x10, [x19, #16]
 cbnz x10, restore_paint
 str xzr, [x19, #8]
 str x9, [x19, #288]
 b restore_paint
restore_bad:
 mov x9, #2
 str x9, [x19, #8]
 mov x9, #41
 str x9, [x19, #16]
 str xzr, [x19, #288]
restore_paint:
 constant x9, PAINT_PA
 br x9

.org 0xb00
.global irq_entry, irq_context_saved
irq_entry:
 // First3GP registers held in zero-owned SYS scratch, never an unknown stack.
 msr tpidr_el1, x0
 msr tpidr_el0, x1
 msr tpidrro_el0, x2
 constant x0, 0x881606000
 mrs x1, sctlr_el1
 tbz x1, #0, irq_unarmed
 at s1e1w, x0
 isb
 mrs x1, par_el1
 tbnz x1, #0, irq_no_record
 constant x2, 0x000ffffffffff000
 and x1, x1, x2
 cmp x1, x0
 b.ne irq_no_record
 mrs x1, CurrentEL
 cmp x1, #4
 b.ne irq_unarmed
 mrs x1, spsel
 cmp x1, #1
 b.ne irq_unarmed
 mov x1, sp
 constant x2, 0xfffffff007c04000
 cmp x1, x2
 b.ne irq_unarmed
 ldr x1, [x0, #1024]
 constant x2, 0x4b31364952514f4e
 cmp x1, x2
 b.ne irq_unarmed
 ldr x1, [x0, #1040]
 ldr x2, [x0, #1048]
 orr x1, x1, x2
 cbnz x1, irq_unarmed
 ldr x1, [x0, #1136]
 cmp x1, #1
 b.ne irq_unarmed
 add x0, x0, #3072
.irp r,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30
 str x\r, [x0, #(\r*8)]
.endr
 mrs x1, tpidr_el1
 str x1, [x0]
 mrs x1, tpidr_el0
 str x1, [x0, #8]
 mrs x1, tpidrro_el0
 str x1, [x0, #16]
 msr tpidr_el1, xzr
 msr tpidr_el0, xzr
 msr tpidrro_el0, xzr
 mrs x1, elr_el1
 str x1, [x0, #248]
 mrs x2, spsr_el1
 str x2, [x0, #256]
 mrs x3, sp_el0
 str x3, [x0, #264]
 constant x4, 0x4b31365245545552
 str x4, [x0, #272]
irq_context_saved:
 constant x19, 0x881606000
 mov x9, #1
 str x9, [x19, #1040]
 str x9, [x19, #1048]
 str xzr, [x19, #1024]
 str x1, [x19, #1152]
 str x2, [x19, #1144]
 mov x9, sp
 str x9, [x19, #1208]
 mrs x9, ICC_IAR1_EL1
 str x9, [x19, #1168]
 cmp x9, #27
 b.ne irq_wrong_id
 mrs x9, cntv_ctl_el0
 str x9, [x19, #1176]
 and x9, x9, #7
 cmp x9, #5
 b.ne irq_reject_active
 isb
 mrs x9, cntvct_el0
 str x9, [x19, #1160]
 ldr x10, [x19, #1096]
 cmp x9, x10
 b.lo irq_reject_active
 ldr x10, [x19, #1104]
 cmp x9, x10
 b.hs irq_reject_active
 mov x9, #2
 msr cntv_ctl_el0, x9
 isb
 dsb sy
 mrs x10, cntv_ctl_el0
 str x10, [x19, #1184]
 mov x9, #27
 msr ICC_EOIR1_EL1, x9
 isb
 str x9, [x19, #1192]
 mrs x9, ICC_RPR_EL1
 and x9, x9, #255
 cmp x9, #255
 b.ne irq_reject
.global irq_validate_return
irq_validate_return:
 constant x0, 0x881606c00
 ldr x9, [x0, #248]
 ldr x10, [x19, #1152]
 cmp x9, x10
 b.ne irq_reject
 tst x9, #3
 b.ne irq_reject
 constant x10, WAIT_BEGIN_KVA
 cmp x9, x10
 b.lo irq_reject
 constant x10, WAIT_END_KVA
 cmp x9, x10
 b.hs irq_reject
 ldr x10, [x0, #256]
 ldr x11, [x19, #1144]
 cmp x10, x11
 b.ne irq_reject
 constant x11, 0x3df
 and x11, x10, x11
 constant x12, 0x344
 cmp x11, x12
 b.ne irq_reject
 ldr x11, [x0, #264]
 ldr x12, [x19, #1072]
 cmp x11, x12
 b.ne irq_reject
 ldr x11, [x0, #272]
 constant x12, 0x4b31365245545552
 cmp x11, x12
 b.ne irq_reject
 ldr x11, [x19, #1048]
 cmp x11, #1
 b.ne irq_reject
 msr elr_el1, x9
 msr spsr_el1, x10
 mov x9, #1
 str x9, [x19, #1056]
 str xzr, [x19, #1040]
.irp r,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30
 ldr x\r, [x0, #(\r*8)]
.endr
 ldp x1, x2, [x0, #8]
 ldr x0, [x0]
.global irq_eret
irq_eret:
 eret
irq_wrong_id:
 cmp x9, #1020
 b.hs irq_reject
irq_reject_active:
 mov x10, #2
 msr cntv_ctl_el0, x10
 isb
 dsb sy
 ldr x9, [x19, #1168]
 msr ICC_EOIR1_EL1, x9
 isb
irq_reject:
 mov x10, #1
 mov x12, #1
 constant x9, CAPTURE_PA
 br x9
irq_unarmed:
 mov x10, #1
 mov x12, #1
 constant x9, CAPTURE_PA
 br x9
irq_no_record:
 constant x9, RECORD_HALT_PA
 br x9
