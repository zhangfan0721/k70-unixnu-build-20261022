// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "HandoffCore.h"

static K70_U64 U64(const K70_U8 *P) {
  K70_U64 V = 0; unsigned I;
  for (I = 0; I < 8; I++) V |= (K70_U64)P[I] << (8 * I);
  return V;
}
static int Zero(const K70_U8 *P, K70_SIZE N) {
  K70_SIZE I;
  for (I = 0; I < N; I++) if (P[I]) return 0;
  return 1;
}
int K70HandoffPlan(K70_U64 Base, K70_U64 Capacity, K70_U64 Span,
                    K70_U64 TreeBytes, K70_HANDOFF_LAYOUT *Layout) {
  K70_HANDOFF_LAYOUT P;
  if (!Layout || Base != K70_HANDOFF_BASE || Capacity != K70_HANDOFF_WINDOW ||
      Span != K70_HANDOFF_SPAN || TreeBytes != K70_HANDOFF_TREE_BYTES) return 0;
  // Exact bounded constants make every addition non-overflowing and congruent
  // with the pinned VA base; no caller-provided pointer is dereferenced here.
  P.Base = Base; P.Capacity = Capacity; P.Args = (Base + Span + 16383) & ~16383ULL;
  P.Tree = P.Args + 4096; P.TreeVa = 0xFFFFFFF007004000ULL + P.Tree - Base;
  P.Top = (P.Tree + TreeBytes + 16383) & ~16383ULL; P.TreeBytes = TreeBytes;
  if (Base + Capacity > 0x8B9D00000ULL || P.Top > Base + Capacity - 0x200000) return 0;
  *Layout = P;
  return 1;
}
int K70SeedMetadata(const K70_U8 *Data, K70_SIZE Size) {
  static const K70_U8 Magic[8] = {'K','7','0','S','E','E','D','1'};
  unsigned I;
  if (!Data || Size != K70_SEED_TRAILER_BYTES) return 0;
  for (I = 0; I < 8; I++) if (Data[I] != Magic[I]) return 0;
  if (Data[8] != 1 || !Zero(Data + 9, 3) || Data[12] != 64 || !Zero(Data + 13, 3)) return 0;
  return !Zero(Data + 16, 64);
}
int K70CheckBootArgs(const K70_U8 *Data, K70_SIZE Size, const K70_HANDOFF_LAYOUT *Layout) {
  K70_HANDOFF_LAYOUT P;
  static const K70_U64 Video[6] = {0xB8000000, 1, 5760, 1440, 3200, 32};
  unsigned I;
  if (!Data || Size != 0x480 || !Layout ||
      !K70HandoffPlan(Layout->Base, Layout->Capacity, K70_HANDOFF_SPAN, Layout->TreeBytes, &P)) return 0;
  if (Layout->Args != P.Args || Layout->Tree != P.Tree || Layout->TreeVa != P.TreeVa || Layout->Top != P.Top) return 0;
  if (Data[0] != 2 || Data[1] || Data[2] != 2 || Data[3] || !Zero(Data + 4, 4)) return 0;
  if (U64(Data + 8) != 0xFFFFFFF007004000ULL || U64(Data + 0x10) != P.Base ||
      U64(Data + 0x18) != P.Capacity || U64(Data + 0x20) != P.Top) return 0;
  for (I = 0; I < 6; I++) if (U64(Data + 0x28 + 8 * I) != Video[I]) return 0;
  if (!Zero(Data + 0x58, 8) || U64(Data + 0x60) != P.TreeVa ||
      Data[0x68] != (K70_HANDOFF_TREE_BYTES & 255) || Data[0x69] != (K70_HANDOFF_TREE_BYTES >> 8) ||
      !Zero(Data + 0x6a, 2)) return 0;
  if (Data[0x6c] != '-' || Data[0x6d] != 'v' || !Zero(Data + 0x6e, 0x470 - 0x6e) ||
      U64(Data + 0x470) || U64(Data + 0x478) != P.Capacity) return 0;
  return 1;
}
int K70CheckTree(const K70_U8 *Data, const K70_U8 *Template, K70_SIZE Size,
                  K70_SIZE SeedOffset, const K70_U8 *Seed) {
  K70_SIZE I;
  if (!Data || !Template || !Seed || Size != K70_HANDOFF_TREE_BYTES ||
      SeedOffset > Size - 64 || Zero(Seed, 64)) return 0;
  if (!Zero(Template + SeedOffset, 64)) return 0;
  for (I = 0; I < Size; I++) {
    K70_U8 Expected = (I >= SeedOffset && I < SeedOffset + 64) ? Seed[I - SeedOffset] : Template[I];
    if (Data[I] != Expected) return 0;
  }
  return 1;
}
