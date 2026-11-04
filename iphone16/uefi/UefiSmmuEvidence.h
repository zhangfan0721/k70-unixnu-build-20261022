// SPDX-License-Identifier: MIT
#ifndef K70_UEFI_SMMU_EVIDENCE_H
#define K70_UEFI_SMMU_EVIDENCE_H

// UEFI types are supplied by the caller. This collector has no writer,
// allocator, logger, translation probe, fault recovery, or configuration path.
// It observes only the already used physical SMMU resource in early SEC.
#define UEFI_SMMU_BASE          0x15000000ULL
#define UEFI_SMMU_WINDOW_BYTES  0x000d0000ULL
#define UEFI_SMMU_ROUTES        105U
#define UEFI_SMMU_BANK_WORDS    9U

typedef enum {
  UefiSmmuNotCaptured = 0,
  UefiSmmuCaptured = 1,
  UefiSmmuInvalidResource = 2,
  UefiSmmuUnknownIds = 3
} UEFI_SMMU_STATUS;

typedef struct {
  UINT32 Slot;
  UINT32 Smr;
  UINT32 S2cr;
} UEFI_SMMU_ROUTE;

typedef struct {
  UINT64 Base;
  UINT64 ResourceBytes;
  UINT64 WindowBytes;
  UINT64 PairId;
  UINT64 Counter;
  UINT32 Status;
  UINT32 Cr0;
  UINT32 Id[3];
  UINT32 Bank69[UEFI_SMMU_BANK_WORDS];
  UINT32 RouteCount;
  UINT32 Sid60Matches;
  UINT32 Bank69References;
  UEFI_SMMU_ROUTE Routes[UEFI_SMMU_ROUTES];
} UEFI_SMMU_SNAPSHOT;

typedef UINT32 (*UEFI_SMMU_READ32)(VOID *Context, UINTN Address);

// CB69 uses 128 global 4KiB pages followed by 69 context pages. The last
// two words are GR1_CBAR69 and GR1_CBA2R69, rather than CB-page registers.
STATIC CONST UINT32 UefiSmmuBankOffsets[UEFI_SMMU_BANK_WORDS] = {
  0xc5000, 0xc5020, 0xc5024, 0xc5028, 0xc502c,
  0xc5030, 0xc5058, 0x1114, 0x1914
};

STATIC BOOLEAN
UefiSmmuWordFits (UINT64 Bytes, UINT32 Offset)
{
  return !(Offset & 3U) && Bytes >= 4 && Offset <= Bytes - 4;
}

STATIC VOID
UefiSmmuCapture (
  UEFI_SMMU_SNAPSHOT *Snapshot,
  UINT64 Base,
  UINT64 ResourceBytes,
  UINT64 PairId,
  UINT64 Counter,
  UEFI_SMMU_READ32 Read,
  VOID *Context)
{
  UINT32 i;

  // Reset a reused static snapshot, including unused route entries. This is
  // fixed RAM storage, not a firmware allocator or an MMIO write.
  *Snapshot = (UEFI_SMMU_SNAPSHOT){0};
  Snapshot->Base = Base;
  Snapshot->ResourceBytes = ResourceBytes;
  Snapshot->WindowBytes = UEFI_SMMU_WINDOW_BYTES;
  Snapshot->PairId = PairId;
  Snapshot->Counter = Counter;
  Snapshot->Status = UefiSmmuInvalidResource;
  if (Base != UEFI_SMMU_BASE || ResourceBytes < UEFI_SMMU_WINDOW_BYTES ||
      ResourceBytes - 1 > ~(UINT64)0 - Base ||
      Base > (UINT64)(~(UINTN)0) - (UEFI_SMMU_WINDOW_BYTES - 1) ||
      !UefiSmmuWordFits (ResourceBytes, 0xc5058) || Read == 0) {
    return;
  }

  // Only these three bounded, architected ID reads precede validation.
  // An unknown implementation never reaches CR0, bank69, or route reads.
  for (i = 0; i < 3; ++i) {
    Snapshot->Id[i] = Read (Context, (UINTN)(Base + 0x20 + 4 * i));
  }
  Snapshot->Status = UefiSmmuUnknownIds;
  if (Snapshot->Id[0] != 0x4c017e69U ||
      Snapshot->Id[1] != 0x60000046U ||
      Snapshot->Id[2] != 0x00005111U) {
    return;
  }

  Snapshot->Cr0 = Read (Context, (UINTN)Base);
  for (i = 0; i < UEFI_SMMU_BANK_WORDS; ++i) {
    Snapshot->Bank69[i] = Read (Context, (UINTN)(Base + UefiSmmuBankOffsets[i]));
  }
  for (i = 0; i < UEFI_SMMU_ROUTES; ++i) {
    UINT32 Smr = Read (Context, (UINTN)(Base + 0x800 + 4 * i));
    UINT32 S2cr;
    UINT32 Mask;
    UEFI_SMMU_ROUTE *Route;
    if (!(Smr & 0x80000000U)) {
      continue;
    }
    S2cr = Read (Context, (UINTN)(Base + 0xc00 + 4 * i));
    Route = &Snapshot->Routes[Snapshot->RouteCount++];
    Route->Slot = i;
    Route->Smr = Smr;
    Route->S2cr = S2cr;
    Mask = (Smr >> 16) & 0x7fffU;
    if (!(((Smr ^ 0x60U) & 0x7fffU) & ~Mask)) {
      ++Snapshot->Sid60Matches;
    }
    // Include every valid reference, including FAULT and BYPASS types.
    if ((S2cr & 0xffU) == 69) {
      ++Snapshot->Bank69References;
    }
  }
  Snapshot->Status = UefiSmmuCaptured;
}

#endif
