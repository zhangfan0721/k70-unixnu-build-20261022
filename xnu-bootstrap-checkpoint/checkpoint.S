// Original firstCPU prefix enters here BEFORE common_start's TCR instruction.
// All diagnostics are stack-free, naturally aligned, and halt.
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
 b.ne checkpoint_register_bad
.endm
.global kernel_checkpoint_begin
.global kernel_checkpoint_halt
.global checkpoint_paint
kernel_checkpoint_begin:
 mov x10, #0
 mov x9, #0
 b save_record

.macro vector id
.global exception_vector_\id
exception_vector_\id:
 mov x10, #1
 mov x9, #\id
 b save_record
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

save_record:
 constant x19, 0x881606000
 constant x11, 0x4b3730424f4f5438
 str x11, [x19]
 str x10, [x19, #8]
 str x9, [x19, #16]
 mrs x11, CurrentEL
 str x11, [x19, #24]
 mrs x11, sctlr_el1
 str x11, [x19, #32]
 mrs x11, vbar_el1
 str x11, [x19, #40]
 mov x11, #0
 str x11, [x19, #48]
 str x11, [x19, #56]
 str x11, [x19, #64]
 cmp x10, #1
 b.ne 1f
 mrs x11, esr_el1
 str x11, [x19, #48]
 mrs x11, elr_el1
 str x11, [x19, #56]
 mrs x11, far_el1
 str x11, [x19, #64]
1:
 mov x11, sp
 str x11, [x19, #72]
 str x30, [x19, #80]
 str x20, [x19, #88]
 str x21, [x19, #96]
 str x22, [x19, #104]
 str x23, [x19, #112]
 str x24, [x19, #120]
 str x25, [x19, #128]
 str x26, [x19, #136]
 cbnz x10, checkpoint_paint
 adr x9, kernel_checkpoint_begin
 equal x9, 0x8803fb290
 ldr x9, [x19, #24]
 equal x9, 4
 ldr x9, [x19, #32]
 constant x11, 0x1005
 tst x9, x11
 b.ne checkpoint_register_bad
 ldr x9, [x19, #40]
 equal x9, 0x8803fa000
 equal x20, 0x881548000
 equal x21, 0
 equal x22, 0xfffffff007004000
 equal x23, 0x880004000
 equal x24, 0x10000000
 equal x25, 0x88017a000
 equal x26, 0
 ldr x9, [x19, #72]
 equal x9, 0xfffffff007bfc000
 ldr x9, [x19, #80]
 equal x9, 0xfffffff0079e5e34
 mrs x9, tpidr_el0
 equal x9, 0
 mrs x9, tpidrro_el0
 equal x9, 0
 // Read and compare EVERY entry in the original 64KiB table pool.
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
 b.ne checkpoint_table_bad
 add x13, x13, #1
 cmp x13, #2, lsl #12
 b.lo table_loop
 b checkpoint_paint
checkpoint_register_bad:
 mov x9, #1
 b checkpoint_bad
checkpoint_table_bad:
 mov x9, #2
checkpoint_bad:
 mov x10, #2
 str x10, [x19, #8]
 str x9, [x19, #16]
checkpoint_paint:
 constant x9, 0xb80b4000
 ldr x10, [x19, #8]
 cbnz x10, paint_failure
 constant x10, 0xff0070ff
 constant x11, 184320
 bl paint_pixels
 constant x10, 0xffffffff
 constant x11, 184320
 bl paint_pixels
 constant x10, 0xff00ff00
 constant x11, 92160
 bl paint_pixels
 b draw_record
paint_failure:
 constant x10, 0xffff0000
 constant x11, 460800
 bl paint_pixels
 b draw_record
paint_pixels:
 str w10, [x9], #4
 subs x11, x11, #1
 b.ne paint_pixels
 dsb sy
 ret

draw_record:
 mov x20, #0
draw_line:
 constant x22, 0xb82d0000 // framebuffer row512
 add x22, x22, #192 // 48pixel left margin protects row IDs at the glass edge.
 constant x9, 276480 // 48rows * 5760bytes
 madd x22, x20, x9, x22
 lsr x0, x20, #4
 mov x1, x22
 bl draw_glyph
 and x0, x20, #15
 add x1, x22, #144
 bl draw_glyph
 add x9, x20, #1
 ldr x21, [x19, x9, lsl #3]
 mov x23, #0
draw_digit:
 mov x24, #60
 sub x24, x24, x23, lsl #2
 lsr x0, x21, x24
 and x0, x0, #15
 mov x9, #144
 madd x1, x23, x9, x22
 add x1, x1, #432
 bl draw_glyph
 add x23, x23, #1
 cmp x23, #16
 b.lo draw_digit
 add x20, x20, #1
 cmp x20, #17
 b.lo draw_line
 dsb sy
 b kernel_checkpoint_halt

// x0=hex nibble, x1=glyph origin. Clobber x9..x18 only; no stack.
draw_glyph:
 adr x9, hex_font
 mov x10, #7
 madd x9, x0, x10, x9
 mov x10, #0
glyph_row:
 ldrb w11, [x9, x10]
 mov x12, #0
glyph_column:
 constant x14, 0xff000000
 cmp x12, #5
 b.eq glyph_color_ready
 mov x13, #4
 sub x13, x13, x12
 lsr x13, x11, x13
 tbz x13, #0, glyph_color_ready
 constant x14, 0xffffffff
glyph_color_ready:
 mov x15, #0
glyph_scale_row:
 mov x17, #6
 madd x18, x10, x17, x15
 constant x16, 5760
 mul x18, x18, x16
 add x18, x18, x1
 mul x16, x12, x17
 add x18, x18, x16, lsl #2
 mov x16, #6
glyph_scale_column:
 str w14, [x18], #4
 subs x16, x16, #1
 b.ne glyph_scale_column
 add x15, x15, #1
 cmp x15, #6
 b.lo glyph_scale_row
 add x12, x12, #1
 cmp x12, #6
 b.lo glyph_column
 add x10, x10, #1
 cmp x10, #7
 b.lo glyph_row
 ret

kernel_checkpoint_halt:
 wfe
 b kernel_checkpoint_halt
hex_font:
.byte 14,17,17,17,17,17,14
.byte 4,12,4,4,4,4,14
.byte 14,17,1,2,4,8,31
.byte 30,1,1,14,1,1,30
.byte 2,6,10,18,31,2,2
.byte 31,16,16,30,1,1,30
.byte 14,16,16,30,17,17,14
.byte 31,1,2,4,8,8,8
.byte 14,17,17,14,17,17,14
.byte 14,17,17,15,1,1,14
.byte 14,17,17,31,17,17,17
.byte 30,17,17,30,17,17,30
.byte 14,17,16,16,16,17,14
.byte 30,17,17,17,17,17,30
.byte 31,16,16,30,16,16,31
.byte 31,16,16,30,16,16,16
.balign 4

