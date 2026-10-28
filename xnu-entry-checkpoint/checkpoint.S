// Diagnostic replacement for start_first_cpu, NOT original XNU CPU init.
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
 b.ne checkpoint_bad
.endm
.global kernel_checkpoint_begin
.global kernel_checkpoint_halt
kernel_checkpoint_begin:
 adr x9, kernel_checkpoint_begin
 equal x9, 0x8803fb05c
 equal x0, 0x881548000
 mrs x9, CurrentEL
 equal x9, 4
 mrs x9, sctlr_el1
 constant x11, 0x1005
 tst x9, x11
 b.ne checkpoint_bad
 ldr w9, [x0]
 equal x9, 0x00020002
 ldr x9, [x0, #8]
 equal x9, 0xfffffff007004000
 ldr x9, [x0, #16]
 equal x9, 0x880004000
 ldr x9, [x0, #24]
 equal x9, 0x10000000
 ldr x9, [x0, #32]
 equal x9, 0x88154c000
 ldr x9, [x0, #0x60]
 equal x9, 0xfffffff008549000
 ldr w9, [x0, #0x68]
 equal x9, 0x6bc
 constant x12, 0x881549000
 ldr x9, [x12]
 equal x9, 0x0000000600000005
 // Seed belongs to the validated ADT and must remain nonzero after EBS.
 add x12, x12, #0x154
 mov x13, #8
 mov x14, #0
1: ldr x9, [x12], #8
 orr x14, x14, x9
 subs x13, x13, #1
 b.ne 1b
 cbz x14, checkpoint_bad
 constant x9, 0xb80b4000 // row 128, 5760 bytes per row
 constant x10, 0xff0070ff
 constant x11, 184320 // 128 rows * 1440 pixels
2: str w10, [x9], #4
 subs x11, x11, #1
 b.ne 2b
 constant x10, 0xffffffff
 constant x11, 184320
3: str w10, [x9], #4
 subs x11, x11, #1
 b.ne 3b
 dsb sy
 b kernel_checkpoint_halt
checkpoint_bad:
 constant x9, 0xb80b4000
 constant x10, 0xffff0000
 constant x11, 368640
4: str w10, [x9], #4
 subs x11, x11, #1
 b.ne 4b
 dsb sy
kernel_checkpoint_halt:
 wfe
 b kernel_checkpoint_halt
