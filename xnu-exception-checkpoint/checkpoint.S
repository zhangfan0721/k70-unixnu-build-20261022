// Stage13: execute original BL/RET/header read; intercept BEFORE conditional.
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
.macro physical_bridge label
 adr x13, \label
 adr x14, kernel_checkpoint_begin
 sub x13, x13, x14
 constant x14, 0x881608000
 add x13, x13, x14
 br x13
.endm
.global kernel_checkpoint_begin, pre_switch_gate, checkpoint_paint, kernel_checkpoint_halt
.global checkpoint_cleanup_phys, record_unavailable_phys
.global clean_c_frame, clean_c_frame_end, frame_cleanup_unavailable_halt
kernel_checkpoint_begin:
 b probe_entry

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
 // Original common_start sets x19=x30; retain its expected C-save value and FP.
 constant x9, 0x881606000
 str x30, [x9, #768]
 str x29, [x9, #776]
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

// Dedicated stage14 record: visible IDs00..23; no handler stack accesses.
.global deliberate_brk, post_capture_complete
.macro require_record
 at s1e1w, x19
 isb
 mrs x2, par_el1
 tbnz x2, #0, record_unavailable
 constant x11, 0x000ffffffffff000
 and x2, x2, x11
 cmp x2, x19
 b.ne record_unavailable
.endm
.macro same_slots pre, post
 ldr x9, [x19, #\pre]
 ldr x13, [x19, #\post]
 cmp x9, x13
 b.ne checkpoint_cleanup
.endm
probe_entry:
 mov x15, x8
 mov x16, x9
 mov x17, x19
 constant x19, 0x881606000
 mrs x18, sctlr_el1
 tbz x18, #0, pre_bad
 require_record
 constant x9, 0x314b524234314b
 str x9, [x19]
 mov x9, #2
 str x9, [x19, #8] // Fail by default. Normal entry is never PASS.
 str xzr, [x19, #288]
 mov x9, sp
 str x9, [x19, #104]
 mrs x9, spsel
 str x9, [x19, #112]
 mrs x9, CurrentEL
 str x9, [x19, #120]
 str x18, [x19, #128]
 mrs x9, vbar_el1
 str x9, [x19, #136]
 mrs x9, tcr_el1
 str x9, [x19, #144]
 mrs x9, ttbr0_el1
 str x9, [x19, #160]
 mrs x9, ttbr1_el1
 str x9, [x19, #176]
 mrs x9, mair_el1
 str x9, [x19, #192]
 adr x9, deliberate_brk
 str x9, [x19, #208]
 constant x9, 0xf2004b14
 str x9, [x19, #216]
 str x16, [x19, #232]
 str x15, [x19, #240]
 str x0, [x19, #248]
 str x29, [x19, #264]
 str x30, [x19, #1048]
 equal x0, 0xfffffff008548000, pre_bad
 equal x17, 0xfffffff008548000, pre_bad
 equal x15, 0xfffffff007004000, pre_bad
 equal x16, 0x200001, pre_bad
 equal x29, 0xfffffff007bfbff0, pre_bad
 equal x30, 0xfffffff0079e5e74, pre_bad
 ldr x9, [x19, #104]
 equal x9, 0xfffffff007bfbf30, pre_bad
 ldr x9, [x19, #112]
 cbnz x9, pre_bad
 ldr x9, [x19, #120]
 equal x9, 4, pre_bad
 constant x11, 0x1005
 and x9, x18, x11
 cmp x9, x11
 b.ne pre_bad
 ldr x9, [x19, #136]
 equal x9, 0x8803fa000, pre_bad
 ldr x9, [x19, #144]
 equal x9, 0x22a51a251a, pre_bad
 ldr x9, [x19, #160]
 equal x9, 0x88017a000, pre_bad
 ldr x9, [x19, #176]
 equal x9, 0x88017b000, pre_bad
 ldr x9, [x19, #192]
 equal x9, 0x0c0804ff00bb44ff, pre_bad
 mrs x9, cpacr_el1
 equal x9, 0x300000, pre_bad
 mrs x9, tpidr_el1
 cbnz x9, pre_bad
 // Pre-C register save values must still match all twelve original saves.
 constant x9, 0xfffffff007bfbf30
 at s1e1r, x9
 isb
 mrs x2, par_el1
 tbnz x2, #0, pre_frame_bad
 constant x11, 0x000ffffffffff000
 and x2, x2, x11
 equal x2, 0x880bfb000, pre_frame_bad
.macro frame_pair offset, first, second
 ldp x1, x2, [x9, #\offset]
 cmp x1, \first
 b.ne pre_frame_bad
 cmp x2, \second
 b.ne pre_frame_bad
.endm
 frame_pair 0x70, x28, x27
 frame_pair 0x80, x26, x25
 frame_pair 0x90, x24, x23
 frame_pair 0xa0, x22, x21
 ldr x3, [x19, #768]
 frame_pair 0xb0, x20, x3
 ldr x4, [x19, #776]
 frame_pair 0xc0, x4, x3
 ldr x1, [x9, #0x68]
 cbnz x1, pre_frame_bad
 ldr w1, [x9, #0x34]
 cbnz w1, pre_frame_bad
 ldp x1, x2, [x9, #0x38]
 orr x1, x1, x2
 cbnz x1, pre_frame_bad
 mrs x9, daif
 and x9, x9, #0x3c0
 equal x9, 0x3c0, pre_bad
 // Nothing below changes flags before BRK. Save only defined comparison bits.
 mrs x9, nzcv
 mrs x13, daif
 and x13, x13, #0x3c0
 orr x9, x9, x13
 orr x9, x9, #4
 str x9, [x19, #1040]
 mov x9, #1
 str x9, [x19, #224]
 constant x9, 0x4b313442524b4152
 str x9, [x19, #1024]
 dsb sy
 isb
deliberate_brk:
 brk #0x4b14
 // A debugger or bad model skipping BRK must not create a success result.
 mov x12, #18
 b pre_reject
pre_frame_bad:
 mov x12, #17
 b pre_reject
pre_bad:
 mov x12, #16
pre_reject:
 mov x10, #2
 b capture_start

capture_start:
 mrs x18, sctlr_el1
 constant x19, 0x881606000
 tbz x18, #0, capture_access_ok
 require_record
capture_access_ok:
 ldr x9, [x19, #1032]
 cbnz x9, record_unavailable
 mov x9, #1
 str x9, [x19, #1032]
 constant x9, 0x314b524234314b
 str x9, [x19]
 stp x10, x12, [x19, #8]
 mrs x9, CurrentEL
 stp x9, x18, [x19, #24]
 mrs x9, vbar_el1
 str x9, [x19, #40]
 mov x9, #0
 mov x11, #0
 mov x13, #0
 mov x14, #0
 cmp x10, #1
 b.ne 1f
 mrs x9, esr_el1
 mrs x11, elr_el1
 mrs x13, far_el1
 mrs x14, spsr_el1
1:
 stp x9, x11, [x19, #48]
 str x13, [x19, #64]
 str x14, [x19, #88]
 mov x9, sp
 stp x9, x30, [x19, #72]
 mrs x9, spsel
 str x9, [x19, #96]
 mrs x9, tcr_el1
 str x9, [x19, #152]
 mrs x9, ttbr0_el1
 str x9, [x19, #168]
 mrs x9, ttbr1_el1
 str x9, [x19, #184]
 mrs x9, mair_el1
 str x9, [x19, #200]
 str x0, [x19, #256]
 str x29, [x19, #272]
 str xzr, [x19, #280] // BRK does not attest a FAR fault address.
 str xzr, [x19, #288]
post_capture_complete:
 ldr x15, [x19, #1024]
 str xzr, [x19, #1024] // One-shot consume, including rejected exceptions.
 cmp x10, #1
 b.ne checkpoint_cleanup
 cbnz x12, checkpoint_cleanup // Actual EL1t synchronous vector must be0.
 equal x15, 0x4b313442524b4152, checkpoint_cleanup
 ldr x9, [x19, #224]
 equal x9, 1, checkpoint_cleanup
 ldr x9, [x19, #48]
 equal x9, 0xf2004b14, checkpoint_cleanup
 ldr x9, [x19, #216]
 equal x9, 0xf2004b14, checkpoint_cleanup
 // Handler executes at a physical alias; derive the expected trigger KVA.
 adr x13, deliberate_brk
 adr x14, kernel_checkpoint_begin
 sub x13, x13, x14
 constant x14, 0xfffffff008608000
 add x13, x13, x14
 ldr x9, [x19, #56]
 cmp x9, x13
 b.ne checkpoint_cleanup
 ldr x9, [x19, #208]
 cmp x9, x13
 b.ne checkpoint_cleanup
 ldr x9, [x19, #88]
 constant x11, 0xf00003df
 and x9, x9, x11
 ldr x13, [x19, #1040]
 cmp x9, x13
 b.ne checkpoint_cleanup
 ldr x9, [x19, #24]
 equal x9, 4, checkpoint_cleanup
 ldr x9, [x19, #112]
 cbnz x9, checkpoint_cleanup
 ldr x9, [x19, #96]
 equal x9, 1, checkpoint_cleanup
 ldr x9, [x19, #104]
 equal x9, 0xfffffff007bfbf30, checkpoint_cleanup
 ldr x9, [x19, #72]
 equal x9, 0xfffffff007c04000, checkpoint_cleanup
 ldr x9, [x19, #80]
 equal x9, 0xfffffff0079e5e74, checkpoint_cleanup
 same_slots 1048, 80
 same_slots 120, 24
 same_slots 128, 32
 same_slots 136, 40
 same_slots 144, 152
 same_slots 160, 168
 same_slots 176, 184
 same_slots 192, 200
 same_slots 248, 256
 same_slots 264, 272
 ldr x9, [x19, #232]
 equal x9, 0x200001, checkpoint_cleanup
 ldr x9, [x19, #240]
 equal x9, 0xfffffff007004000, checkpoint_cleanup
 // All evidence captured and verified; only now is this expected exception PASS.
 stp xzr, xzr, [x19, #8]
 mov x9, #2
 str x9, [x19, #224]
 mov x9, #1
 str x9, [x19, #288]
 b checkpoint_cleanup

checkpoint_cleanup:
 physical_bridge checkpoint_cleanup_phys
checkpoint_cleanup_phys:
 mrs x9, sctlr_el1
 tbz x9, #0, checkpoint_paint
clean_c_frame:
 // Both mappings and the cache geometry are checked before the first DC.
 require_record
 constant x1, 0xfffffff007bfbf30
 at s1e1w, x1
 isb
 mrs x2, par_el1
 tbnz x2, #0, record_unavailable
 constant x11, 0x000ffffffffff000
 and x2, x2, x11
 equal x2, 0x880bfb000, record_unavailable
 mrs x7, ctr_el0
 ubfx x7, x7, #16, #4
 mov x2, #4
 lsl x7, x2, x7
 cmp x7, #16
 b.lo record_unavailable
 cmp x7, #1, lsl #12
 b.hi record_unavailable
 sub x2, x7, #1
 bic x6, x1, x2
 constant x8, 0xfffffff007bfc000
clean_frame_loop:
 dc civac, x6
 add x6, x6, x7
 cmp x6, x8
 b.lo clean_frame_loop
 mov x6, x19
 add x8, x19, #4096
clean_record_loop:
 dc civac, x6
 add x6, x6, x7
 cmp x6, x8
 b.lo clean_record_loop
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
clean_c_frame_end:

record_unavailable:
 physical_bridge record_unavailable_phys
record_unavailable_phys:
frame_cleanup_unavailable_halt:
 wfe
 b frame_cleanup_unavailable_halt
kernel_checkpoint_halt:
 wfe
 b kernel_checkpoint_halt
