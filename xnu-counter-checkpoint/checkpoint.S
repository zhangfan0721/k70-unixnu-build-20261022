// Stage15: bounded read-only counter progression after original caller/RET.
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
 constant x9, 0x31544e4335314b
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
 b counter_begin
pre_frame_bad:
 mov x12, #17
 b pre_reject
pre_bad:
 mov x12, #16
pre_reject:
 mov x10, #2
 b capture_start

counter_begin:
 // Only after the original frame/ABI contract: initialize the new schema.
 str x16, [x19, #240]
 str x15, [x19, #248]
 mov x9, #1
 str x9, [x19, #272]
 str xzr, [x19, #280]
 str xzr, [x19, #288]
 str xzr, [x19, #16]
 add x1, x19, #96
 add x2, x19, #208
counter_zero:
 str xzr, [x1], #8
 cmp x1, x2
 b.lo counter_zero
 mov x9, #1
 str x9, [x19, #1152] // Schema ready. Counter fields no longer contain old snapshots.
 isb
.global counter_frequency_before
counter_frequency_before:
 mrs x9, cntfrq_el0
 str x9, [x19, #96]
 cbz x9, counter_bad_frequency
 mov x11, #0xca00
 movk x11, #0x3b9a, lsl #16 // 1,000,000,000Hz diagnostic bound.
 cmp x9, x11
 b.hi counter_bad_frequency
 isb
.global counter_sample_0_physical
counter_sample_0_physical:
 mrs x9, cntpct_el0
 str x9, [x19, #112]
 isb
.global counter_sample_0_virtual
counter_sample_0_virtual:
 mrs x9, cntvct_el0
 str x9, [x19, #144]
 mov x5, #4096
.global counter_wait_first
counter_wait_first:
 subs x5, x5, #1
 b.ne counter_wait_first
 mov x9, #4096
 str x9, [x19, #176]
 isb
.global counter_sample_1_physical
counter_sample_1_physical:
 mrs x9, cntpct_el0
 str x9, [x19, #120]
 isb
.global counter_sample_1_virtual
counter_sample_1_virtual:
 mrs x9, cntvct_el0
 str x9, [x19, #152]
 mov x5, #8192
.global counter_wait_second
counter_wait_second:
 subs x5, x5, #1
 b.ne counter_wait_second
 mov x9, #8192
 str x9, [x19, #184]
 isb
.global counter_sample_2_physical
counter_sample_2_physical:
 mrs x9, cntpct_el0
 str x9, [x19, #128]
 isb
.global counter_sample_2_virtual
counter_sample_2_virtual:
 mrs x9, cntvct_el0
 str x9, [x19, #160]
 mov x9, #3
 str x9, [x19, #192]
 isb
.global counter_frequency_after
counter_frequency_after:
 mrs x9, cntfrq_el0
 str x9, [x19, #104]
 ldr x1, [x19, #96]
 cmp x9, x1
 b.ne counter_bad_frequency
 .macro increasing offset, failure
 ldp x1, x2, [x19, #\offset]
 cmp x2, x1
 b.ls \failure
 .endm
 increasing 112, counter_bad_physical
 increasing 120, counter_bad_physical
 increasing 144, counter_bad_virtual
 increasing 152, counter_bad_virtual
 ldr x4, [x19, #96]
 ldr x1, [x19, #112]
 ldr x2, [x19, #128]
 sub x3, x2, x1
 cmp x3, x4
 b.hs counter_bad_physical
 str x3, [x19, #136]
 ldr x1, [x19, #144]
 ldr x2, [x19, #160]
 sub x3, x2, x1
 cmp x3, x4
 b.hs counter_bad_virtual
 str x3, [x19, #168]
 constant x9, 0x4b3135434e54524f
 str x9, [x19, #1024]
.global counter_validated
counter_validated:
 mov x10, #0
 mov x12, #0
 b capture_start
counter_bad_frequency:
 mov x12, #20
 b pre_reject
counter_bad_physical:
 mov x12, #21
 b pre_reject
counter_bad_virtual:
 mov x12, #22
 b pre_reject

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
 constant x9, 0x31544e4335314b
 str x9, [x19]
 // Incoming normal completion is a failure until its one-shot proof passes.
 mov x9, #2
 cbz x10, 1f
 mov x9, x10
1:
 stp x9, x12, [x19, #8]
 str xzr, [x19, #288]
 ldr x9, [x19, #1152]
 cmp x9, #1
 b.eq counter_record_ready
 add x1, x19, #96
 add x2, x19, #208
counter_reject_zero:
 str xzr, [x1], #8
 cmp x1, x2
 b.lo counter_reject_zero
 stp xzr, xzr, [x19, #240]
 str xzr, [x19, #272]
counter_record_ready:
 str xzr, [x19, #280]
 mrs x9, CurrentEL
 stp x9, x18, [x19, #24]
 mrs x9, vbar_el1
 str x9, [x19, #40]
 mov x9, #0
 mov x11, #0
 mov x13, #0
 mov x14, #0
 cmp x10, #1
 b.ne 2f
 mrs x9, esr_el1
 mrs x11, elr_el1
 mrs x13, far_el1
 mrs x14, spsr_el1
2:
 stp x9, x11, [x19, #48]
 str x13, [x19, #64]
 str x14, [x19, #200]
 mov x9, sp
 stp x9, x30, [x19, #72]
 mrs x9, spsel
 str x9, [x19, #88]
 mrs x9, tcr_el1
 str x9, [x19, #208]
 mrs x9, ttbr0_el1
 str x9, [x19, #216]
 mrs x9, ttbr1_el1
 str x9, [x19, #224]
 mrs x9, mair_el1
 str x9, [x19, #232]
 str x0, [x19, #256]
 str x29, [x19, #264]
.global post_capture_complete
post_capture_complete:
 ldr x15, [x19, #1024]
 str xzr, [x19, #1024]
 cbnz x10, checkpoint_cleanup // Every vector rejects even with a forged token.
 ldr x9, [x19, #1152]
 cmp x9, #1
 b.ne counter_rejected_completion
 equal x15, 0x4b3135434e54524f, counter_rejected_completion
 stp xzr, xzr, [x19, #8]
 mov x9, #1
 str x9, [x19, #288]
 b checkpoint_cleanup
counter_rejected_completion:
 mov x9, #24
 str x9, [x19, #16]
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
