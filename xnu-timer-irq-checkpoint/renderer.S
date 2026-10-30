// Runs only after XNU MMU/cache disable. Stack-free two-column hex renderer.
.text
.macro constant reg, value
 movz \reg, #(\value & 0xffff)
 movk \reg, #((\value >> 16) & 0xffff), lsl #16
 movk \reg, #((\value >> 32) & 0xffff), lsl #32
 movk \reg, #((\value >> 48) & 0xffff), lsl #48
.endm
.global checkpoint_paint
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
 constant x10, 0xff00ffff
 constant x11, 92160
 bl paint_pixels
 constant x10, 0xffff00ff
 constant x11, 92160
 bl paint_pixels
 constant x10, 0xffffff00
 constant x11, 92160
 bl paint_pixels
 b draw_record
paint_failure:
 constant x10, 0xffff0000
 constant x11, 737280
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
 constant x22, 0xb83de000 // row704, x40
 add x22, x22, #160
 mov x9, x20
 cmp x9, #18
 b.lo 1f
 sub x9, x9, #18
 add x22, x22, #2880 //720pixels
1:
 constant x10, 218880 //38rows*5760
 madd x22, x9, x10, x22
 lsr x0, x20, #4
 mov x1, x22
 bl draw_glyph
 and x0, x20, #15
 add x1, x22, #120
 bl draw_glyph
 add x9, x20, #1
 ldr x21, [x19, x9, lsl #3]
 mov x23, #0
draw_digit:
 mov x24, #60
 sub x24, x24, x23, lsl #2
 lsr x0, x21, x24
 and x0, x0, #15
 mov x9, #120
 madd x1, x23, x9, x22
 add x1, x1, #360
 bl draw_glyph
 add x23, x23, #1
 cmp x23, #16
 b.lo draw_digit
 add x20, x20, #1
 cmp x20, #36
 b.lo draw_line
 dsb sy
 b kernel_checkpoint_halt

// x0=nibble, x1=glyph origin; preserves x19..x30. No stack.
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
 mov x17, #5
 madd x18, x10, x17, x15
 constant x16, 5760
 mul x18, x18, x16
 add x18, x18, x1
 mul x16, x12, x17
 add x18, x18, x16, lsl #2
 mov x16, #5
glyph_scale_column:
 str w14, [x18], #4
 subs x16, x16, #1
 b.ne glyph_scale_column
 add x15, x15, #1
 cmp x15, #5
 b.lo glyph_scale_row
 add x12, x12, #1
 cmp x12, #6
 b.lo glyph_column
 add x10, x10, #1
 cmp x10, #7
 b.lo glyph_row
 ret
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

