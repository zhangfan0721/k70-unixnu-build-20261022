// Stage16: bounded virtual timer IRQ and transparent integer-context return.
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
.global exception_vector_1
exception_vector_1:
 constant x9, 0x881604b00
 br x9
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
 b irq_begin
pre_frame_bad:
 mov x12, #17
 b pre_reject
pre_bad:
 mov x12, #16
pre_reject:
 mov x10, #2
 b capture_start


.macro save_gp base
.irp r,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30
 str x\r, [x19, #(\base + \r*8)]
.endr
.endm
irq_begin:
 add x1, x19, #8
 add x2, x19, #296
1: str xzr, [x1], #8
 cmp x1, x2
 b.lo 1b
 add x1, x19, #1024
 add x2, x19, #1264
2: str xzr, [x1], #8
 cmp x1, x2
 b.lo 2b
 mov x9, #1
 str x9, [x19, #1136]
 str x9, [x19, #280] // Original C frame checked.
 mrs x9, tpidr_el0
 cbnz x9, irq_bad
 mrs x9, tpidrro_el0
 cbnz x9, irq_bad
 ldr x9, [x19, #640]
 cmp x9, #1
 b.ne irq_bad
 mov x9, sp
 str x9, [x19, #1072]
 msr spsel, #1
 mov x9, sp
 msr spsel, #0
 str x9, [x19, #1064]
 equal x9, 0xfffffff007c04000, irq_bad
 mrs x9, cntfrq_el0
 str x9, [x19, #1080]
 constant x11, 1000000
 cmp x9, x11
 b.lo irq_bad
 constant x11, 1000000000
 cmp x9, x11
 b.hi irq_bad
 lsr x10, x9, #15
 cmp x10, #32
 mov x11, #32
 csel x10, x10, x11, hs
 lsr x11, x9, #8
 isb
 mrs x9, cntvct_el0
 str x9, [x19, #1088]
 adds x10, x9, x10
 b.cs irq_bad
 str x10, [x19, #1096]
 adds x11, x9, x11
 b.cs irq_bad
 str x11, [x19, #1104]
 msr cntv_cval_el0, x10
 mov x12, #1
 lsl x12, x12, #16
 str x12, [x19, #1112]
 constant x9, 0x4b31364952514f4e
 str x9, [x19, #1024]
 save_gp 1536
.global irq_arm
irq_arm:
 mov x9, #1
 msr cntv_ctl_el0, x9
 isb
 msr daifclr, #2
.global irq_wait_begin, irq_wait_end, irq_returned
irq_wait_begin:
 ldr x9, [x19, #1056]
 cbnz x9, irq_returned
 isb
 mrs x10, cntvct_el0
 ldr x11, [x19, #1104]
 cmp x10, x11
 b.hs irq_wait_end
 subs x12, x12, #1
 b.ne irq_wait_begin
irq_wait_end:
 msr daifset, #15
 mov x12, #32
 b pre_reject
irq_returned:
 msr daifset, #15
 save_gp 2048
 mov x1, #0
 mov x5, #0
 constant x6, 0x7fffe1ff
3: lsr x2, x6, x1
 tbz x2, #0, 4f
 add x3, x19, #1536
 add x4, x19, #2048
 ldr x2, [x3, x1, lsl #3]
 ldr x3, [x4, x1, lsl #3]
 cmp x2, x3
 b.ne irq_bad
 orr x5, x5, x2 // Comparison result, never a substitute for per-reg equality.
4: add x1, x1, #1
 cmp x1, #31
 b.lo 3b
 str x6, [x19, #1128]
 mov x9, #1
 ldr x10, [x19, #1048]
 cmp x10, x9
 b.ne irq_bad
 ldr x10, [x19, #1056]
 cmp x10, x9
 b.ne irq_bad
 mrs x10, CurrentEL
 cmp x10, #4
 b.ne irq_bad
 str x10, [x19, #1224]
 mrs x10, spsel
 cbnz x10, irq_bad
 mov x10, sp
 ldr x11, [x19, #1072]
 cmp x10, x11
 b.ne irq_bad
 msr spsel, #1
 mov x10, sp
 msr spsel, #0
 str x10, [x19, #1216]
 ldr x11, [x19, #1064]
 cmp x10, x11
 b.ne irq_bad
 mrs x10, tpidr_el1
 mrs x11, tpidr_el0
 orr x10, x10, x11
 mrs x11, tpidrro_el0
 orr x10, x10, x11
 cbnz x10, irq_bad
 mrs x10, cntfrq_el0
 str x10, [x19, #1256]
 ldr x11, [x19, #1080]
 cmp x10, x11
 b.ne irq_bad
 isb
 mrs x10, cntvct_el0
 str x10, [x19, #1248]
 ldr x11, [x19, #1160]
 cmp x10, x11
 b.lo irq_bad
 ldr x11, [x19, #1104]
 cmp x10, x11
 b.hs irq_bad
 ldr x11, [x19, #1112]
 sub x11, x11, x12
 str x11, [x19, #1120]
 str x9, [x19, #1200]
 mov x10, #0
 mov x12, #0
 b capture_start
irq_bad:
 mov x12, #33
 b pre_reject

.global capture_start
capture_start:
 msr daifset, #15
 mrs x18, sctlr_el1
 constant x19, 0x881606000
 tbz x18, #0, capture_access_ok
 require_record
capture_access_ok:
 ldr x9, [x19, #1032]
 cbnz x9, record_unavailable
 mov x9, #1
 str x9, [x19, #1032]
 constant x9, 0x3151524936314b
 str x9, [x19]
 mov x9, #2
 cbz x10, 1f
 mov x9, x10
 str xzr, [x19, #1200]
1: stp x9, x12, [x19, #8]
 str xzr, [x19, #288]
 mrs x9, CurrentEL
 stp x9, x18, [x19, #24]
 mrs x9, vbar_el1
 str x9, [x19, #40]
 adr x1, field_sources
 mov x2, #5
2: ldrh w3, [x1], #2
 ldr x4, [x19, x3]
 add x3, x2, #1
 str x4, [x19, x3, lsl #3]
 add x2, x2, #1
 cmp x2, #33
 b.lo 2b
 // Last three fields are explicit state, never stale prior-schema snapshots.
 str xzr, [x19, #272]
 ldr x9, [x19, #1136]
 str x9, [x19, #280]
 str xzr, [x19, #288]
 ldr x9, [x19, #664]
 ubfx x9, x9, #1, #1
 str x9, [x19, #160]
 ldr x9, [x19, #632]
 cbz x9, checkpoint_cleanup
 mov x9, #2
 msr cntv_ctl_el0, x9
 msr ICC_IGRPEN1_EL1, xzr
 isb
.global post_capture_complete
post_capture_complete:
 b checkpoint_cleanup
.balign 2
field_sources:
.hword 1168,1152,1144,1072,2288,1048,1080,1088,1096,1160,1248
.hword 1176,1184,1192,664,1200,1064,1208,1216,1128,1120
.hword 528,512,520,656,536,544,680
.balign 4

checkpoint_cleanup:
 physical_bridge checkpoint_cleanup_phys
checkpoint_cleanup_phys:
 mrs x9, sctlr_el1
 tbz x9, #0, to_gic_restore
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
 b to_gic_restore
clean_c_frame_end:
to_gic_restore:
 constant x9, 0x881604700
 br x9

record_unavailable:
 physical_bridge record_unavailable_phys
record_unavailable_phys:
 msr daifset, #15
 mov x9, #2
 msr cntv_ctl_el0, x9
 msr ICC_IGRPEN1_EL1, xzr
 isb
frame_cleanup_unavailable_halt:
 wfe
 b frame_cleanup_unavailable_halt
kernel_checkpoint_halt:
 wfe
 b kernel_checkpoint_halt

