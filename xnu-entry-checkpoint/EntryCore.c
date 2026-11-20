// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "EntryCore.h"

int K70EntryCacheProfile(K70_U64 Ctr) {
  unsigned D = (unsigned)((Ctr >> 16) & 15), I = (unsigned)(Ctr & 15);
  return D >= 2 && D <= 10 && I >= 2 && I <= 10;
}

int K70EntryWalk(K70_U64 Tcr, K70_U64 Ttbr, K70_U64 Mair, K70_U64 Va,
                  K70_READ_PTE Read, void *Context, K70_ENTRY_PAGE *Result) {
  const K70_U64 AddressMask = 0x0000FFFFFFFFF000ULL;
  const K70_U64 PaMask = ((1ULL << 40) - 1) & ~4095ULL;
  K70_U64 Table, Descriptor, Address, Flags, Size, Physical, Xn;
  unsigned Level, Shift, Index;
  K70_ENTRY_PAGE P;
  if (!Read || !Result || (Tcr & 63) != 24 || ((Tcr >> 14) & 3) ||
      ((Tcr >> 32) & 7) != 2 || (Tcr & ((1ULL << 7) | (1ULL << 59))) ||
      Va >= (1ULL << 40) || (Ttbr & 0xffe)) return 0;
  Table = Ttbr & AddressMask;
  if (!Table || (Table & ~PaMask)) return 0;
  for (Level = 0; Level < 4; Level++) {
    Shift = 39 - 9 * Level;
    Index = (unsigned)((Va >> Shift) & 511);
    if (!Read(Context, Table + 8 * Index, &Descriptor)) return 0;
    if (!(Descriptor & 1)) return 0;
    Address = Descriptor & AddressMask;
    if (Address & ~PaMask) return 0;
    if (Level < 3 && (Descriptor & 3) == 3) {
      // No inherited permissions or non-secure table overrides are assumed.
      if (!Address || (Descriptor >> 59)) return 0;
      Table = Address;
      continue;
    }
    if ((Level == 0) || (Level < 3 && (Descriptor & 3) != 1) ||
        (Level == 3 && (Descriptor & 3) != 3)) return 0;
    Size = 1ULL << Shift;
    if (Address & (Size - 1)) return 0;
    // This probe supports only the observed ordinary EL1 WB RAM profile.
    // Reject device/NC/WT, EL0-accessible pages, AF=0, non-inner-shareable,
    // asymmetric XN, and LPA/DBM/contiguous profiles rather than guessing.
    if (((Mair >> (8 * ((Descriptor >> 2) & 7))) & 255) != 255 ||
        !(Descriptor & (1ULL << 10)) || (Descriptor & (1ULL << 6)) ||
        ((Descriptor >> 8) & 3) != 3 || (Descriptor & (31ULL << 48))) return 0;
    Xn = (Descriptor >> 53) & 3;
    if (Xn != 0 && Xn != 3) return 0;
    Physical = Address | (Va & (Size - 1));
    Flags = K70_ENTRY_WB | ((Descriptor & (1ULL << 7)) ? K70_ENTRY_RO : 0) |
            (Xn ? K70_ENTRY_XP : 0);
    P.Physical = Physical; P.Flags = Flags; P.Level = Level; P.Raw = Descriptor;
    *Result = P;
    return 1;
  }
  return 0;
}

int K70EntryScopes(K70_U64 Base, K70_U64 Capacity, K70_U64 Span,
                    K70_U64 StubBytes, K70_U64 TransitionBytes, K70_U64 Pages[3]) {
  if (!Pages || Base != 0x880004000ULL || Capacity != 0x10000000ULL || Span != 0x1544000ULL ||
      !StubBytes || StubBytes > 4096 - 0x5c || !TransitionBytes || TransitionBytes > 4096) return 0;
  Pages[0] = Base + 0x3f5000; Pages[1] = Base + 0x3f7000; Pages[2] = Base + 0x1600000;
  return 1;
}

int K70ExitDecision(unsigned Attempt, int MapOk, int ExitCode) {
  if (Attempt >= 3) return K70_EXIT_HALT;
  if (!MapOk) return Attempt == 0 ? K70_EXIT_RETURN : K70_EXIT_HALT;
  if (ExitCode == 0) return K70_EXIT_ENTER;
  if (ExitCode == 1 && Attempt < 2) return K70_EXIT_RETRY;
  return K70_EXIT_HALT;
}
