// SPDX-License-Identifier: BSD-2-Clause-Patent
// Instrumented earliest-entry witness only. Never resumes original CPU init.
#include <Uefi.h>
#include <PiDxe.h>
#include <Protocol/Cpu.h>
#include <Library/BaseLib.h>
#include <Library/BaseMemoryLib.h>
#include <Library/BaseCryptLib.h>
#include <Library/CacheMaintenanceLib.h>
#include <Library/DebugLib.h>
#include <Library/DxeServicesTableLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include "Entry.h"
#include "EntryCore.h"
#include "EntryBlobs.h"

typedef struct {
  UINT64 Tcr, Ttbr, Mair;
} K70_REGS;
typedef VOID (*K70_TRANSITION)(UINT64, UINT64, UINT64, UINT64, UINT64, UINT64);

STATIC VOID K70Halt(VOID) {
  for (;;) __asm__ volatile("wfe");
}
STATIC BOOLEAN Identity(UINT64 Address) {
  UINT64 Par;
  if (Address >= (1ULL << 40)) return FALSE;
  __asm__ volatile("at s1e1r, %1\n\tisb\n\tmrs %0, par_el1" : "=r"(Par) : "r"(Address) : "memory");
  return !(Par & 1) && (Par & 0x0000FFFFFFFFF000ULL) == (Address & ~4095ULL);
}
STATIC int ReadPte(void *Context, K70_U64 Address, K70_U64 *Value) {
  EFI_GCD_MEMORY_SPACE_DESCRIPTOR Region;
  UINT64 Page = Address & ~4095ULL;
  (VOID)Context;
  if ((Address & 7) || Address >= (1ULL << 40) || !Value ||
      EFI_ERROR(gDS->GetMemorySpaceDescriptor(Page, &Region)) ||
      Region.GcdMemoryType != EfiGcdMemoryTypeSystemMemory ||
      Region.BaseAddress > Page || Region.Length < 4096 ||
      Page - Region.BaseAddress > Region.Length - 4096 ||
      !Identity(Page) || !Identity(Page + 4095)) return 0;
  *Value = *(volatile UINT64 *)(UINTN)Address;
  return 1;
}
STATIC BOOLEAN PageInfo(CONST K70_REGS *Regs, UINT64 Address, K70_ENTRY_PAGE *Info) {
  return K70EntryWalk(Regs->Tcr, Regs->Ttbr, Regs->Mair, Address, ReadPte, NULL, Info) &&
         Info->Physical == Address && Identity(Address);
}
STATIC UINT64 Attributes(UINT64 Flags) {
  return EFI_MEMORY_WB | ((Flags & K70_ENTRY_RO) ? EFI_MEMORY_RO : 0) |
         ((Flags & K70_ENTRY_XP) ? EFI_MEMORY_XP : 0);
}

EFI_STATUS K70EntryCheckpoint(EFI_HANDLE ImageHandle, UINT64 Base, UINTN Capacity, UINT64 Span) {
  EFI_CPU_ARCH_PROTOCOL *Cpu = NULL;
  K70_REGS Regs;
  K70_ENTRY_PAGE Before[3], Now;
  K70_U64 Pages[3];
  UINT8 Digest[32];
  UINTN I, Changed = 0, Need = 0, MapCapacity = 0, MapBytes, Key, DescriptorBytes;
  UINT32 DescriptorVersion;
  EFI_MEMORY_DESCRIPTOR *Map = NULL;
  EFI_STATUS Status = EFI_ABORTED, Restore;
  UINT64 El, Sctlr, Ctr, Daif = 0, Address;
  BOOLEAN DaifSaved = FALSE, Restored = TRUE;
  unsigned Attempt;
  int Decision;
  K70_TRANSITION Enter = (K70_TRANSITION)(UINTN)0x881604000ULL;
  __asm__ volatile("mrs %0, CurrentEL" : "=r"(El));
  __asm__ volatile("mrs %0, sctlr_el1" : "=r"(Sctlr));
  __asm__ volatile("mrs %0, tcr_el1" : "=r"(Regs.Tcr));
  __asm__ volatile("mrs %0, ttbr0_el1" : "=r"(Regs.Ttbr));
  __asm__ volatile("mrs %0, mair_el1" : "=r"(Regs.Mair));
  __asm__ volatile("mrs %0, ctr_el0" : "=r"(Ctr));
  if (El != 4 || (Sctlr & 0x1005) != 0x1005 ||
      !K70EntryCacheProfile(Ctr) ||
      !K70EntryScopes(Base, Capacity, Span, sizeof(mEntryStub), sizeof(mEntryTransition), Pages) ||
      EFI_ERROR(gBS->LocateProtocol(&gEfiCpuArchProtocolGuid, NULL, (VOID **)&Cpu)) ||
      Cpu == NULL || Cpu->SetMemoryAttributes == NULL) goto Fail;
  // No arbitrary PTE dereference: table pages must be GCD system RAM and identity-mapped.
  // Every page of the entire owned allocation must retain an identity translation.
  for (Address = Base; Address < Base + Capacity; Address += 4096)
    if (!Identity(Address)) goto Fail;
  if (!Identity(0xb8000000ULL) || !Identity(0xb9193fffULL)) goto Fail;
  for (I = 0; I < 3; I++)
    if (!PageInfo(&Regs, Pages[I], &Before[I])) goto Fail;
  if ((Before[1].Flags | Before[2].Flags) & K70_ENTRY_RO) goto Fail;
  if (CompareMem((VOID *)(UINTN)(Base + 0x3f705c), mEntryOriginalPatch, sizeof(mEntryOriginalPatch)) ||
      *(volatile UINT32 *)(UINTN)(Base + 0x3f5488) != 0x140006f5 ||
      !Sha256HashAll(mEntryStub, sizeof(mEntryStub), Digest) || CompareMem(Digest, mEntryStubHash, 32) ||
      !Sha256HashAll(mEntryTransition, sizeof(mEntryTransition), Digest) || CompareMem(Digest, mEntryTransitionHash, 32))
    goto Fail;
  CopyMem((VOID *)(UINTN)(Base + 0x3f705c), mEntryStub, sizeof(mEntryStub));
  CopyMem((VOID *)(UINTN)Pages[2], mEntryTransition, sizeof(mEntryTransition));
  if (!Sha256HashAll((VOID *)(UINTN)Base, (UINTN)Span, Digest) || CompareMem(Digest, mEntryMappedHash, 32) ||
      CompareMem((VOID *)(UINTN)Pages[2], mEntryTransition, sizeof(mEntryTransition)) ||
      *(volatile UINT32 *)(UINTN)(Base + 0x3f5488) != 0x140006f5) goto Fail;
  // Reserve generous slack before changing attributes (splitting page tables may allocate).
  Status = gBS->GetMemoryMap(&Need, NULL, &Key, &DescriptorBytes, &DescriptorVersion);
  if (Status != EFI_BUFFER_TOO_SMALL || !Need || Need > 0xf0000 || !DescriptorBytes ||
      DescriptorBytes > 4096) goto Fail;
  MapCapacity = Need + 65536;
  Map = AllocatePool(MapCapacity);
  if (Map == NULL) { Status = EFI_OUT_OF_RESOURCES; goto Fail; }
  for (I = 0; I < 3; I++) {
    // Include this page in rollback even if the provider reports a partial failure.
    Changed = I + 1;
    Status = Cpu->SetMemoryAttributes(Cpu, Pages[I], 4096, EFI_MEMORY_WB | EFI_MEMORY_RO);
    if (EFI_ERROR(Status) || !PageInfo(&Regs, Pages[I], &Now) ||
        Now.Flags != (K70_ENTRY_WB | K70_ENTRY_RO)) goto Fail;
  }
  // Publish the new instruction stream BEFORE its first instruction fetch.
  // Pinned ArmCacheMaintenanceLib provides DSB/ISB; validated CTR line sizes
  // divide these aligned 4KiB pages, so no adjacent allocation is touched.
  for (I = 0; I < 3; I++) {
    WriteBackDataCacheRange((VOID *)(UINTN)Pages[I], 4096);
    InvalidateInstructionCacheRange((VOID *)(UINTN)Pages[I], 4096);
  }
  if (gST->ConOut != NULL) gST->ConOut->ClearScreen(gST->ConOut);
  // Leave at least 384 pixels even for a small 12-pixel console font.
  for (I = 0; I < 32; I++) DEBUG((DEBUG_ERROR, "\n"));
  DEBUG((DEBUG_ERROR, "K70 INSTRUMENTED KERNEL ENTRY CHECKPOINT\n"));
  DEBUG((DEBUG_ERROR, "Original __start branch preserved; first-CPU body instrumented\nNo partition writes; no original CPU init or userland\n"));
  DEBUG((DEBUG_ERROR, "TCR %016lx  TTBR0 %016lx\nMAIR %016lx  SCTLR %016lx\n", Regs.Tcr, Regs.Ttbr, Regs.Mair, Sctlr));
  for (I = 0; I < 3; I++) DEBUG((DEBUG_ERROR, "OWNED CODE RO+X PAGE %lx\n", Pages[I]));
  DEBUG((DEBUG_ERROR, "PATCH / IMAGE HASH OK; IDENTITY WINDOW VERIFIED\n"));
  DEBUG((DEBUG_ERROR, "Purple: copied transition; orange: MMU off\nBlue + white: instrumented kernel-text checkpoint PASS\nRed: checkpoint rejected input\n"));
  DEBUG((DEBUG_ERROR, "After checkpoint: Power + VolDown for FASTBOOT\nPREPARING EXIT BOOT SERVICES\n"));
  __asm__ volatile("mrs %0, daif\n\tmsr daifset, #15\n\tisb" : "=r"(Daif) :: "memory");
  DaifSaved = TRUE;
  for (Attempt = 0; Attempt < 3; Attempt++) {
    MapBytes = MapCapacity;
    Status = gBS->GetMemoryMap(&MapBytes, Map, &Key, &DescriptorBytes, &DescriptorVersion);
    if (EFI_ERROR(Status)) {
      Decision = K70ExitDecision(Attempt, 0, 2);
    } else {
      Status = gBS->ExitBootServices(ImageHandle, Key);
      Decision = K70ExitDecision(Attempt, 1, !EFI_ERROR(Status) ? 0 : (Status == EFI_INVALID_PARAMETER ? 1 : 2));
    }
    if (Decision == K70_EXIT_RETURN) goto Fail;
    if (Decision == K70_EXIT_RETRY) continue;
    if (Decision == K70_EXIT_ENTER) {
      // No further UEFI calls, stack use in the blob, or return after this point.
      Enter(0x881548000ULL, 0x8803f9488ULL, Base, Capacity, 0xb8000000ULL, 0x1194000ULL);
    }
    K70Halt();
  }
  K70Halt();
Fail:
  // Reachable only before the first ExitBootServices attempt.
  while (Changed) {
    I = --Changed;
    Restore = Cpu->SetMemoryAttributes(Cpu, Pages[I], 4096, Attributes(Before[I].Flags));
    if (EFI_ERROR(Restore) || !PageInfo(&Regs, Pages[I], &Now) || Now.Flags != Before[I].Flags)
      Restored = FALSE;
  }
  if (DaifSaved) __asm__ volatile("msr daif, %0\n\tisb" :: "r"(Daif) : "memory");
  if (!Restored) {
    DEBUG((DEBUG_ERROR, "FAIL: page permission restore; RAM retained. Power + VolDown\n"));
    K70Halt();
  }
  if (Map != NULL) FreePool(Map);
  DEBUG((DEBUG_ERROR, "ENTRY PREPARATION REJECTED (%r); UEFI retained\n", Status));
  return EFI_ERROR(Status) ? Status : EFI_ABORTED;
}

