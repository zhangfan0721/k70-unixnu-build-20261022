// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "GuardCore.h"

static K70_U64 Read64(const K70_U8 *P) {
  K70_U64 V = 0; unsigned I;
  for (I = 0; I < 8; I++) V |= (K70_U64)P[I] << (I * 8);
  return V;
}

int K70CpuSupportsXnu(K70_U64 Mmfr0) {
  unsigned Pa = (unsigned)(Mmfr0 & 15), Granule = (unsigned)((Mmfr0 >> 28) & 15);
  return Pa >= 2 && Pa <= 6 && Granule == 0;
}

int K70DataRange(const void *Map, K70_SIZE Bytes, K70_SIZE Stride,
                 K70_U64 Start, K70_U64 Length) {
  const K70_U8 *Data = (const K70_U8 *)Map;
  const K70_U64 Limit = 1ULL << 40;
  K70_U64 Cursor, End, Base, Pages, Top, Next, Boundary;
  K70_SIZE I;
  unsigned Matches;
  if (!Data || !Bytes || Stride < 40 || Stride > 4096 || Bytes % Stride ||
      !Length || (Start & 4095) || (Length & 4095) || Start >= Limit || Length > Limit - Start)
    return 0;
  End = Start + Length; Cursor = Start;
  while (Cursor < End) {
    Matches = 0; Next = Cursor; Boundary = End;
    for (I = 0; I < Bytes; I += Stride) {
      Base = Read64(Data + I + 8); Pages = Read64(Data + I + 24);
      if (!Pages) continue;
      if ((Base & 4095) || Base >= Limit || Pages > (Limit - Base) / 4096) return 0;
      Top = Base + Pages * 4096;
      // Visit every descriptor boundary, including a conflicting nested range.
      if (Cursor < Base && Base < Boundary) Boundary = Base;
      if (Base <= Cursor && Cursor < Top) {
        // EFI_LOADER_DATA=2, with the standard little-endian descriptor ABI.
        if (++Matches != 1 || Data[I] != 2 || Data[I+1] || Data[I+2] || Data[I+3]) return 0;
        Next = Top < End ? Top : End;
      }
    }
    if (Matches != 1 || Next <= Cursor) return 0;
    Cursor = Next < Boundary ? Next : Boundary;
  }
  return 1;
}
