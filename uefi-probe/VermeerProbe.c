// SPDX-License-Identifier: BSD-2-Clause-Patent
// Observe CPU/GOP/memory without ExitBootServices, MMIO writes or disk access.
#include <Uefi.h>
#include <Library/BaseLib.h>
#include <Library/DebugLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/UefiApplicationEntryPoint.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiLib.h>
#include <Protocol/GraphicsOutput.h>

#define READ_REG(Name) Read##Name ()
#define REGISTER_READER(Name, Register) \
  STATIC UINT64 Read##Name (VOID) { UINT64 Value; __asm__ volatile ("mrs %0, " #Register : "=r" (Value)); return Value; }
REGISTER_READER (El, CurrentEL)
REGISTER_READER (Midr, midr_el1)
REGISTER_READER (Mpidr, mpidr_el1)
REGISTER_READER (Counter, cntfrq_el0)
REGISTER_READER (Mmfr, id_aa64mmfr0_el1)
REGISTER_READER (Pfr, id_aa64pfr0_el1)

STATIC
UINT64
FreeRunEnd (EFI_MEMORY_DESCRIPTOR *Map, UINTN Size, UINTN Stride, UINT64 End)
{
  BOOLEAN Changed;
  UINTN Offset;
  EFI_MEMORY_DESCRIPTOR *Entry;
  do {
    Changed = FALSE;
    for (Offset = 0; Offset + Stride <= Size; Offset += Stride) {
      Entry = (EFI_MEMORY_DESCRIPTOR *)((UINT8 *)Map + Offset);
      if (Entry->Type == EfiConventionalMemory && Entry->PhysicalStart == End &&
          Entry->NumberOfPages != 0 && Entry->NumberOfPages <= (MAX_UINT64 - End) / EFI_PAGE_SIZE) {
        End += EFI_PAGES_TO_SIZE (Entry->NumberOfPages);
        Changed = TRUE;
      }
    }
  } while (Changed);
  return End;
}

EFI_STATUS
EFIAPI
VermeerProbeEntry (EFI_HANDLE ImageHandle, EFI_SYSTEM_TABLE *SystemTable)
{
  EFI_GRAPHICS_OUTPUT_PROTOCOL *Gop;
  EFI_MEMORY_DESCRIPTOR *Map = NULL, *Entry;
  EFI_STATUS Status;
  UINTN Size = 0, Capacity, Key, Stride = 0, Offset;
  UINT32 Version;
  UINT64 BestBase = 0, BestBytes = 0, End, Candidate, Bytes;
  EFI_INPUT_KEY Input;

  (VOID)ImageHandle;
  (VOID)SystemTable;
  gBS->SetWatchdogTimer (0, 0, 0, NULL);
  if (gST->ConOut != NULL) { gST->ConOut->ClearScreen (gST->ConOut); }
  // The framebuffer debug renderer and ConOut have independent cursors.
  // Use the debug renderer alone so the CPU values remain readable.
  DEBUG ((DEBUG_ERROR, "\fVERMEER CPU / GOP / RAM PROBE\nNo kernel jump; no disk access\nFirmware RAM map only; not a RAM test\n\n"));
  DEBUG ((DEBUG_ERROR, "EL %lu  MIDR %lx\nMPIDR %lx  AFF %lx\nCNTFRQ %lu Hz\nMMFR0 %lx  PFR0 %lx\n",
          READ_REG (El) >> 2, READ_REG (Midr), READ_REG (Mpidr), READ_REG (Mpidr) & 0xFF00FFFFFFULL,
          READ_REG (Counter), READ_REG (Mmfr), READ_REG (Pfr)));
  Status = gBS->LocateProtocol (&gEfiGraphicsOutputProtocolGuid, NULL, (VOID **)&Gop);
  if (!EFI_ERROR (Status) && Gop->Mode != NULL && Gop->Mode->Info != NULL) {
    DEBUG ((DEBUG_ERROR, "GOP FB %lx  SIZE %lx\n%ux%u  STRIDE %u  FORMAT %u\n",
            Gop->Mode->FrameBufferBase, (UINT64)Gop->Mode->FrameBufferSize,
            Gop->Mode->Info->HorizontalResolution, Gop->Mode->Info->VerticalResolution,
            Gop->Mode->Info->PixelsPerScanLine, Gop->Mode->Info->PixelFormat));
  } else {
    DEBUG ((DEBUG_ERROR, "GOP unavailable %r\n", Status));
  }
  Status = gBS->GetMemoryMap (&Size, NULL, &Key, &Stride, &Version);
  if (Status == EFI_BUFFER_TOO_SMALL && Stride >= sizeof (EFI_MEMORY_DESCRIPTOR)) {
    Capacity = Size + 16 * Stride;
    Map = AllocatePool (Capacity);
    if (Map != NULL) {
      Size = Capacity;
      Status = gBS->GetMemoryMap (&Size, Map, &Key, &Stride, &Version);
      if (!EFI_ERROR (Status)) {
        for (Offset = 0; Offset + Stride <= Size; Offset += Stride) {
          Entry = (EFI_MEMORY_DESCRIPTOR *)((UINT8 *)Map + Offset);
          if (Entry->Type != EfiConventionalMemory || Entry->NumberOfPages == 0 ||
              Entry->NumberOfPages > (MAX_UINT64 - Entry->PhysicalStart) / EFI_PAGE_SIZE) { continue; }
          End = FreeRunEnd (Map, Size, Stride, Entry->PhysicalStart + EFI_PAGES_TO_SIZE (Entry->NumberOfPages));
          // Match DarwinBoot's 2 MiB block alignment and this XNU's 0x4000 base offset.
          if (Entry->PhysicalStart > MAX_UINT64 - 0x204000) { continue; }
          Candidate = ALIGN_VALUE (Entry->PhysicalStart, 0x200000) + 0x4000;
          if (End <= Candidate) { continue; }
          Bytes = End - Candidate;
          if (Bytes > BestBytes) { BestBase = Candidate; BestBytes = Bytes; }
          DEBUG ((DEBUG_ERROR, "FREE %lx..%lx CANDIDATE %lx\n", Entry->PhysicalStart, End, Candidate));
        }
      }
      FreePool (Map);
    } else { Status = EFI_OUT_OF_RESOURCES; }
  }
  DEBUG ((DEBUG_ERROR, "MAP %r\nLARGEST WINDOW %lx @ %lx\nRAM WINDOW NOT HARDWARE-VERIFIED\n", Status, BestBytes, BestBase));
  DEBUG ((DEBUG_ERROR, "GIC stock: 17100000 / 17180000\nSTRIDE stock: 40000\n\nPHOTO THESE VALUES\nAny key returns to UEFI\nPower + VolDown: fastboot\n"));
  for (;;) {
    gBS->Stall (100000);
    if (gST->ConIn != NULL && !EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, &Input))) { break; }
  }
  return EFI_SUCCESS;
}

