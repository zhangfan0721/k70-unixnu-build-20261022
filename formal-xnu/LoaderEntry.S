// SPDX-License-Identifier: BSD-2-Clause-Patent
// Based on pinned UniXNU/DarwinBoot Entry.S; x0/x1 remain the handoff arguments.
#include <AsmMacroLib.h>

ASM_FUNC(DarwinCurrentEl)
  mrs x0, CurrentEL
  ret

// K70-only, bounded 200-row marker. x16/x17 preserve the supplied PA/size.
// Repaint the same area so the last visible colour identifies one boundary.
.macro K70_LOADER_MARK colour
  mov x14, #0xb8000000
  cmp x16, x14
  b.ne .Lmark_skip\@
  mov x14, #0x4000
  movk x14, #0x119, lsl #16
  cmp x17, x14                  // 1440 * 3200 * 4 bytes
  b.ne .Lmark_skip\@
  lsr x9, x17, #4
  mov w10, #(\colour & 0xffff)
  movk w10, #((\colour >> 16) & 0xffff), lsl #16
  mov x11, x16
.Lpaint\@:
  stp w10, w10, [x11], #8
  subs x9, x9, #8
  b.ne .Lpaint\@
  dsb sy
.Lmark_skip\@:
.endmacro

// EL1 only. x0=args PA, x1=entry PA, x2=owned PA, x3=owned size,
// x4=framebuffer PA (0 for none), x5=framebuffer bytes.
ASM_FUNC(DarwinEnter)
.Lhandoff_start:
  msr daifset, #15
  mov x16, x4
  mov x17, x5
  K70_LOADER_MARK 0xff00ff00     // Green: EBS returned, handoff entered.
  add x5, x2, x3
  mrs x6, ctr_el0
  ubfx x6, x6, #16, #4
  mov x7, #4
  lsl x6, x7, x6
  sub x7, x6, #1
  bic x4, x2, x7
  dsb sy
.Lkernel_clean:
  dc civac, x4
  add x4, x4, x6
  cmp x4, x5
  b.lo .Lkernel_clean

  // PE loading to PoU does not guarantee PoC visibility after disabling I-cache.
  // The kernel allocation is a separate window and cannot cover this code.
  adr x12, .Lhandoff_start
  adr x13, .Lhandoff_end
  bic x12, x12, x7
.Lhandoff_clean:
  dc civac, x12
  add x12, x12, x6
  cmp x12, x13
  b.lo .Lhandoff_clean
  dsb sy
  ic iallu
  dsb sy
  isb
  K70_LOADER_MARK 0xff00ffff     // Cyan: both cache-clean loops completed.
  mrs x4, sctlr_el1
  bic x4, x4, #1
  bic x4, x4, #4
  bic x4, x4, #0x1000
  msr sctlr_el1, x4
  isb
  tlbi vmalle1
  dsb sy
  isb
  K70_LOADER_MARK 0xff0000ff     // Blue: MMU/cache off, immediately before BR.
  br x1
.Lhandoff_end:
