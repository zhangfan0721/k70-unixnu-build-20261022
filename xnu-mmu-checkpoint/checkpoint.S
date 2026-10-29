// Stage09: original common_start programs the MMU; this checkpoint never resumes it.
.text
.macro constant reg, value
 movz \reg, #(\value & 0xffff)
 movk \reg, #((\value >> 16) & 0xffff), lsl #16
 movk \reg, #((\value >> 32) & 0xffff), lsl #32
 movk \reg, #((\value >> 48) & 0xffff), lsl #48
.endm
.macro equal reg, value, failure
 constant x11, \value
 cmp \reg, x11
 b.ne \failure
.endm
.global kernel_checkpoint_begin, pre_switch_gate, checkpoint_paint, kernel_checkpoint_halt
kernel_checkpoint_begin:
 mov x10, #0
 mov x12, #0
 b capture_start

// Replaces only the first ADRP; no BL/stack use and original LR is retained.
pre_switch_gate:
 equal x20, 0x881548000, gate_bad
 equal x21, 0, gate_bad
 equal x22, 0xfffffff007004000, gate_bad
 equal x23, 0x880004000, gate_bad
 equal x24, 0x10000000, gate_bad
 equal x25, 0x88017a000, gate_bad
 equal x26, 0, gate_bad
 mov x9, sp
 equal x9, 0xfffffff007bfc000, gate_bad
 equal x30, 0xfffffff0079e5e34, gate_bad
 mrs x9, CurrentEL
 equal x9, 4, gate_bad
 mrs x9, sctlr_el1
 constant x11, 0x1005
 tst x9, x11
 b.ne gate_bad
 mrs x9, vbar_el1
 equal x9, 0x8803fa000, gate_bad
 constant x9, 0x880177cd0
 ldr x9, [x9]
 equal x9, 0x22a51a251a, gate_bad
 mov x13, #0
table_loop:
 ldr x15, [x25, x13, lsl #3]
 mov x14, #0
 cmp x13, #34
 b.eq table_root_p
 cmp x13, #704
 b.eq table_root_k
 sub x16, x13, #1024
 cmp x16, #128
 b.lo table_leaf
 sub x16, x13, #1592
 cmp x16, #128
 b.lo table_leaf
 b table_compare
table_root_p:
 constant x14, 0x88017c003
 b table_compare
table_root_k:
 constant x14, 0x88017d003
 b table_compare
table_leaf:
 constant x14, 0x880000000
 add x14, x14, x16, lsl #21
 mov x17, #0x601
 orr x14, x14, x17
table_compare:
 cmp x15, x14
 b.ne gate_table_bad
 add x13, x13, #1
 cmp x13, #2, lsl #12
 b.lo table_loop
 constant x0, 0x880177000
 constant x9, 0x8803fb294
 br x9
gate_table_bad:
 mov x12, #2
 b gate_reject
gate_bad:
 mov x12, #1
gate_reject:
 mov x10, #2
 b capture_start

.macro vector n
.global exception_vector_\n
exception_vector_\n:
 mov x10, #1
 mov x12, #\n
 b capture_start
.endm
vector 0
vector 1
vector 2
vector 3
vector 4
vector 5
vector 6
vector 7
vector 8
vector 9
vector 10
vector 11
vector 12
vector 13
vector 14
vector 15

capture_start:
 mrs x18, sctlr_el1
 constant x19, 0x881606000
 tbz x18, #0, capture_record
 // Before the first data write under XNU M1, verify the record is writable.
 at s1e1w, x19
 isb
 mrs x9, par_el1
 tbnz x9, #0, record_unavailable
 constant x11, 0xfffffff000
 and x9, x9, x11
 cmp x9, x19
 b.eq capture_record
record_unavailable:
 constant x11, 0x1005
 bic x9, x18, x11
 msr sctlr_el1, x9
 isb
 tlbi vmalle1
 dsb sy
 isb
 mov x10, #2
 mov x12, #4
capture_record:
 constant x9, 0x394f4e554d4d374b
 str x9, [x19]
 stp x10, x12, [x19, #8]
 mrs x9, CurrentEL
 stp x9, x18, [x19, #24]
 mrs x9, vbar_el1
 str x9, [x19, #40]
 mov x9, #0
 mov x11, #0
 mov x13, #0
 cmp x10, #1
 b.ne 1f
 mrs x9, esr_el1
 mrs x11, elr_el1
 mrs x13, far_el1
1:
 stp x9, x11, [x19, #48]
 str x13, [x19, #64]
 mov x9, sp
 stp x9, x30, [x19, #72]
 stp x20, x21, [x19, #88]
 stp x22, x23, [x19, #104]
 stp x24, x25, [x19, #120]
 str x26, [x19, #136]
 mrs x9, tcr_el1
 mrs x11, ttbr0_el1
 stp x9, x11, [x19, #144]
 mrs x9, ttbr1_el1
 mrs x11, mair_el1
 stp x9, x11, [x19, #160]
 cbnz x10, checkpoint_cleanup
 ldr x9, [x19, #24]
 equal x9, 4, register_bad
 constant x11, 0x1005
 and x9, x18, x11
 cmp x9, x11
 b.ne register_bad
 ldr x9, [x19, #40]
 equal x9, 0x8803fa000, register_bad
 ldr x9, [x19, #144]
 equal x9, 0x22a51a251a, config_bad
 ldr x9, [x19, #152]
 equal x9, 0x88017a000, config_bad
 ldr x9, [x19, #160]
 equal x9, 0x88017b000, config_bad
 ldr x9, [x19, #168]
 equal x9, 0x0c0804ff00bb44ff, config_bad
 equal x20, 0x881548000, register_bad
 equal x21, 0, register_bad
 equal x22, 0xfffffff007004000, register_bad
 equal x23, 0x880004000, register_bad
 equal x24, 0x10000000, register_bad
 equal x25, 0x88017a000, register_bad
 equal x26, 0, register_bad
 ldr x9, [x19, #72]
 equal x9, 0xfffffff007bfc000, register_bad
 ldr x9, [x19, #80]
 equal x9, 0xfffffff0079e5e34, register_bad

.macro translate va, pa, slot, writable=0
 constant x9, \va
 .if \writable
 at s1e1w, x9
 .else
 at s1e1r, x9
 .endif
 isb
 mrs x10, par_el1
 str x10, [x19, #(\slot * 8)]
 tbnz x10, #0, config_bad
 constant x11, 0xfffffff000
 and x10, x10, x11
 equal x10, (\pa & 0xfffffff000), config_bad
.endm
 translate 0x8803f9488, 0x8803f9488, 22
 translate 0xfffffff0073f9488, 0x8803f9488, 23
 translate 0xfffffff008548000, 0x881548000, 24
 translate 0xfffffff007bfbff0, 0x880bfbff0, 25, 1
 translate 0x880000000, 0x880000000, 26
 translate 0x88ffff000, 0x88ffff000, 27
 constant x9, 0x890003000
 at s1e1r, x9
 isb
 mrs x10, par_el1
 str x10, [x19, #224]
 tbz x10, #0, config_bad
 constant x9, 0xfffffff008548000
 ldr w10, [x9]
 str x10, [x19, #232]
 equal x10, 0x00020002, config_bad
 constant x9, 0xfffffff007bfbff0
 ldp x13, x14, [x9]
 constant x15, 0x536b374d4d554f4e
 constant x16, 0xa55a5aa533cccc33
 // Mark before the first potentially dirty stack write. EL1 exception entry
 // preserves this field, so cleanup also covers a fault during the test.
 mov x17, #2
 str x17, [x19, #240]
 stp x15, x16, [x9]
 ldp x17, x18, [x9]
 stp x13, x14, [x9]
 cmp x15, x17
 b.ne stack_bad
 cmp x16, x18
 b.ne stack_bad
 mov x9, #1
 str x9, [x19, #240]
 b checkpoint_cleanup
register_bad:
 mov x12, #1
 b reject
config_bad:
 mov x12, #3
 b reject
stack_bad:
 mov x12, #5
reject:
 mov x10, #2
 stp x10, x12, [x19, #8]

checkpoint_cleanup:
 mrs x9, sctlr_el1
 tbz x9, #0, checkpoint_paint
 // Only touched, mapped cache lines. Never walk the unmapped BA window tail.
 mrs x7, ctr_el0
 ubfx x7, x7, #16, #4
 mov x11, #4
 lsl x7, x11, x7
 mov x6, x19
 add x8, x19, #4096
clean_record:
 dc civac, x6
 add x6, x6, x7
 cmp x6, x8
 b.lo clean_record
 ldr x6, [x19, #240]
 cbz x6, clean_complete
 constant x6, 0xfffffff007bfbff0
 sub x11, x7, #1
 bic x6, x6, x11
 dc civac, x6
 // If a cache line is only16 bytes, the restored pair still fits exactly.
clean_complete:
 dsb sy
 ic iallu
 dsb sy
 isb
 constant x11, 0x1005
 bic x9, x9, x11
 msr sctlr_el1, x9
 isb
 tlbi vmalle1
 dsb sy
 isb
 b checkpoint_paint

kernel_checkpoint_halt:
 wfe
 b kernel_checkpoint_halt
