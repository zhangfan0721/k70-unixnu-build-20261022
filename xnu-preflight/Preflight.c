// SPDX-License-Identifier: BSD-2-Clause-Patent
// Materialize a pinned kernel in owned RAM; never execute or hand off to it.
#include <Uefi.h>
#include <Library/BaseLib.h>
#include <Library/BaseMemoryLib.h>
#include <Library/BaseCryptLib.h>
#include <Library/DebugLib.h>
#include <Library/FdtLib.h>
#include <Library/HobLib.h>
#include <Library/UefiApplicationEntryPoint.h>
#include <Library/UefiBootServicesTableLib.h>
#include "MachoCore.h"
#include "ExpectedPayload.h"

STATIC BOOLEAN ReadFdtNumber(CONST VOID *Tree, INT32 Node, CONST CHAR8 *Name, UINT64 *Value) {
  INT32 Length, I;
  CONST UINT8 *Bytes = FdtGetProp(Tree, Node, Name, &Length);
  if (Bytes == NULL || (Length != 4 && Length != 8)) return FALSE;
  *Value = 0;
  for (I = 0; I < Length; I++) *Value = (*Value << 8) | Bytes[I];
  return TRUE;
}

EFI_STATUS EFIAPI K70PreflightEntry(EFI_HANDLE ImageHandle, EFI_SYSTEM_TABLE *SystemTable) {
  EFI_HOB_GUID_TYPE *Hob;
  EFI_PHYSICAL_ADDRESS Dtb = 0, Destination = 0x880004000ULL;
  UINT64 Initrd = 0, InitrdEnd = 0, TreeBytes, PayloadBytes, Entry, El, Tcr, Sctlr;
  UINTN Pages = 0, I;
  CONST UINT8 *Payload;
  UINT8 Digest[32];
  K70_PLAN Plan;
  EFI_STATUS Status = EFI_ABORTED;
  EFI_INPUT_KEY Key;
  BOOLEAN Allocated = FALSE;
  INT32 Chosen;
  int Result;
  (VOID)ImageHandle; (VOID)SystemTable;
  gBS->SetWatchdogTimer(0, 0, 0, NULL);
  if (gST->ConOut != NULL) gST->ConOut->ClearScreen(gST->ConOut);
  DEBUG((DEBUG_ERROR, "\fK70 XNU LOAD PREFLIGHT - NO JUMP\nNo disk access; no kernel execution\n\n"));
  __asm__ volatile("mrs %0, CurrentEL" : "=r"(El));
  El >>= 2;
  DEBUG((DEBUG_ERROR, "EL %lu  PROFILE: 4096-byte kernel pages\n", El));
  if (El != 1) { DEBUG((DEBUG_ERROR, "FAIL: expected EL1\n")); goto Wait; }
  __asm__ volatile("mrs %0, tcr_el1" : "=r"(Tcr));
  __asm__ volatile("mrs %0, sctlr_el1" : "=r"(Sctlr));
  DEBUG((DEBUG_ERROR, "TCR %lx  SCTLR %lx (unchanged)\n", Tcr, Sctlr));

  Hob = GetFirstGuidHob(&gSiliciumEntryArgHobGuid);
  if (Hob == NULL || GET_GUID_HOB_DATA_SIZE(Hob) < sizeof(Dtb)) {
    DEBUG((DEBUG_ERROR, "FAIL: no boot argument HOB\n")); goto Wait;
  }
  CopyMem(&Dtb, GET_GUID_HOB_DATA(Hob), sizeof(Dtb));
  DEBUG((DEBUG_ERROR, "BOOT FDT %lx\n", Dtb));
  if ((Dtb & 3) || !K70RangeInReserved(Dtb, 40)) {
    DEBUG((DEBUG_ERROR, "FAIL: FDT outside preserved kernel area\n")); goto Wait;
  }
  if (FdtCheckHeader((VOID *)(UINTN)Dtb) != 0) {
    DEBUG((DEBUG_ERROR, "FAIL: FDT header\n")); goto Wait;
  }
  TreeBytes = FdtTotalSize((VOID *)(UINTN)Dtb);
  if (TreeBytes < 40 || TreeBytes > 0x400000 || !K70RangeInReserved(Dtb, TreeBytes)) {
    DEBUG((DEBUG_ERROR, "FAIL: FDT bounds\n")); goto Wait;
  }
  Chosen = FdtPathOffset((VOID *)(UINTN)Dtb, "/chosen");
  if (Chosen < 0 || !ReadFdtNumber((VOID *)(UINTN)Dtb, Chosen, "linux,initrd-start", &Initrd) ||
      !ReadFdtNumber((VOID *)(UINTN)Dtb, Chosen, "linux,initrd-end", &InitrdEnd)) {
    DEBUG((DEBUG_ERROR, "FAIL: no initrd pointers in boot FDT\n")); goto Wait;
  }
  DEBUG((DEBUG_ERROR, "INITRD %lx..%lx\n", Initrd, InitrdEnd));
  if (InitrdEnd <= Initrd) { DEBUG((DEBUG_ERROR, "FAIL: initrd ordering\n")); goto Wait; }
  PayloadBytes = InitrdEnd - Initrd;
  if (PayloadBytes != 128 + K70_EXPECTED_KERNEL_BYTES ||
      !K70RangeInReserved(Initrd, PayloadBytes) ||
      (Initrd < Dtb + TreeBytes && Dtb < InitrdEnd)) {
    DEBUG((DEBUG_ERROR, "FAIL: initrd size/reservation/overlap\n")); goto Wait;
  }
  Payload = (CONST UINT8 *)(UINTN)Initrd;
  Result = K70InspectPayload(Payload, (UINTN)PayloadBytes,
                             mExpectedKernelHash, mExpectedMappedHash, &Plan);
  if (Result != K70_OK || Plan.VmBase != K70_EXPECTED_VM_BASE ||
      Plan.Span != K70_EXPECTED_SPAN || Plan.EntryOffset != K70_EXPECTED_ENTRY_OFFSET) {
    DEBUG((DEBUG_ERROR, "FAIL: payload/Mach-O status %d\n", Result)); goto Wait;
  }
  if (!Sha256HashAll(Payload + 128, K70_EXPECTED_KERNEL_BYTES, Digest) ||
      CompareMem(Digest, mExpectedKernelHash, sizeof(Digest)) != 0) {
    DEBUG((DEBUG_ERROR, "FAIL: kernel SHA256\n")); goto Wait;
  }
  DEBUG((DEBUG_ERROR, "KERNEL SHA256 OK; %lu bytes\n", K70_EXPECTED_KERNEL_BYTES));
  Result = K70Place(&Plan, Destination, 0x8B9D00000ULL, &Entry);
  if (Result != K70_OK) { DEBUG((DEBUG_ERROR, "FAIL: destination placement\n")); goto Wait; }
  Pages = EFI_SIZE_TO_PAGES((UINTN)Plan.Span);
  Status = gBS->AllocatePages(AllocateAddress, EfiLoaderData, Pages, &Destination);
  DEBUG((DEBUG_ERROR, "ALLOCATE %lx + %lx: %r\n", Destination, Plan.Span, Status));
  if (EFI_ERROR(Status)) goto Wait;
  Allocated = TRUE; Status = EFI_ABORTED;
  if (Destination != 0x880004000ULL) { DEBUG((DEBUG_ERROR, "FAIL: unexpected allocated base\n")); goto Wait; }
  Result = K70LoadMachO(Payload + 128, K70_EXPECTED_KERNEL_BYTES,
                        (UINT8 *)(UINTN)Destination, EFI_PAGES_TO_SIZE(Pages), &Plan);
  if (Result != K70_OK) { DEBUG((DEBUG_ERROR, "FAIL: materialize %d\n", Result)); goto Wait; }
  if (!Sha256HashAll((VOID *)(UINTN)Destination, (UINTN)Plan.Span, Digest) ||
      CompareMem(Digest, mExpectedMappedHash, sizeof(Digest)) != 0) {
    DEBUG((DEBUG_ERROR, "FAIL: materialized SHA256\n")); goto Wait;
  }
  for (I = 0; I < Plan.Count; I++) {
    K70_SEGMENT *S = &Plan.Segments[I];
    DEBUG((DEBUG_ERROR, "%a %lx + %lx FILE %lx\n", S->Name,
           Destination + S->Offset, S->Size, S->FileSize));
  }
  DEBUG((DEBUG_ERROR, "\nMATERIALIZED SHA256 OK\nVM BASE %lx  SPAN %lx\n", Plan.VmBase, Plan.Span));
  DEBUG((DEBUG_ERROR, "ENTRY OFFSET %lx\nPHYSICAL ENTRY %lx (not called)\n", Plan.EntryOffset, Entry));
  DEBUG((DEBUG_ERROR, "PREFLIGHT PASS - KERNEL JUMP DISABLED\nboot_args / ADT handoff: NOT BUILT\nMMU/cache/GIC unchanged; services active\n"));
  Status = EFI_SUCCESS;
Wait:
  DEBUG((DEBUG_ERROR, "\nPHOTO THESE VALUES\nAny key frees owned RAM and returns\nPower + VolDown: fastboot\n"));
  for (;;) {
    gBS->Stall(100000);
    if (gST->ConIn != NULL && !EFI_ERROR(gST->ConIn->ReadKeyStroke(gST->ConIn, &Key))) break;
  }
  if (Allocated) gBS->FreePages(Destination, Pages);
  return Status;
}
