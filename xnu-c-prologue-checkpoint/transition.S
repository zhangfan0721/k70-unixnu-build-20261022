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
