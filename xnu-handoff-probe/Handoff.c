// SPDX-License-Identifier: BSD-2-Clause-Patent
// Data preparation only. No kernel function pointer or execution transition.
#include <Uefi.h>
#include <Library/BaseMemoryLib.h>
#include <Library/BaseCryptLib.h>
#include <Library/DebugLib.h>
#include "Handoff.h"
#include "HandoffTemplates.h"

EFI_STATUS K70PrepareHandoff(UINT64 Base, UINTN Capacity, UINT64 Span,
                             CONST UINT8 *SeedTrailer, UINTN TrailerBytes) {
  K70_HANDOFF_LAYOUT P;
  UINT8 Seed[64], Digest[32], ExpectedTreeHash[32], ActualHash[32];
  UINT8 TreeExpected[K70_HANDOFF_TREE_BYTES];
  UINT8 *Args, *Tree;
  UINTN I;
  CHAR8 SeedTag[33];
  CONST CHAR8 Hex[] = "0123456789abcdef";
  EFI_STATUS Status = EFI_COMPROMISED_DATA;
  ZeroMem(Seed, sizeof(Seed)); ZeroMem(TreeExpected, sizeof(TreeExpected));
  if (!K70HandoffPlan(Base, Capacity, Span, sizeof(mHandoffTreeTemplate), &P)) {
    DEBUG((DEBUG_ERROR, "FAIL: whole-window handoff placement\n")); goto Done;
  }
  DEBUG((DEBUG_ERROR, "OWNED WINDOW %lx @ %lx\n", P.Capacity, P.Base));
  // Caller has already bounded this entire 112-byte source inside the initrd
  // reservation. Metadata does not replace the cryptographic integrity check.
  if (!K70SeedMetadata(SeedTrailer, TrailerBytes) ||
      !Sha256HashAll(SeedTrailer, 80, Digest) || CompareMem(Digest, SeedTrailer + 80, 32)) {
    DEBUG((DEBUG_ERROR, "FAIL: private seed trailer; prepare locally before boot\n")); goto Done;
  }
  CopyMem(Seed, SeedTrailer + 16, sizeof(Seed));
  if (!Sha256HashAll(mHandoffArgs, sizeof(mHandoffArgs), Digest) ||
      CompareMem(Digest, mHandoffArgsHash, 32) ||
      !Sha256HashAll(mHandoffTreeTemplate, sizeof(mHandoffTreeTemplate), Digest) ||
      CompareMem(Digest, mHandoffTreeHash, 32) ||
      K70_DATA_SEED_OFFSET > sizeof(TreeExpected) - sizeof(Seed)) {
    DEBUG((DEBUG_ERROR, "FAIL: compiled handoff template\n")); goto Done;
  }
  if (!K70CheckBootArgs(mHandoffArgs, sizeof(mHandoffArgs), &P)) {
    DEBUG((DEBUG_ERROR, "FAIL: boot_args template layout\n")); goto Done;
  }
  CopyMem(TreeExpected, mHandoffTreeTemplate, sizeof(TreeExpected));
  CopyMem(TreeExpected + K70_DATA_SEED_OFFSET, Seed, sizeof(Seed));
  if (!Sha256HashAll(TreeExpected, sizeof(TreeExpected), ExpectedTreeHash)) goto Done;
  Args = (UINT8 *)(UINTN)P.Args; Tree = (UINT8 *)(UINTN)P.Tree;
  CopyMem(Args, mHandoffArgs, sizeof(mHandoffArgs));
  CopyMem(Tree, TreeExpected, sizeof(TreeExpected));
  if (!K70CheckBootArgs(Args, sizeof(mHandoffArgs), &P) ||
      !K70CheckTree(Tree, mHandoffTreeTemplate, sizeof(TreeExpected), K70_DATA_SEED_OFFSET, Seed) ||
      !Sha256HashAll(Args, sizeof(mHandoffArgs), Digest) || CompareMem(Digest, mHandoffArgsHash, 32) ||
      !Sha256HashAll(Tree, sizeof(TreeExpected), ActualHash) || CompareMem(ActualHash, ExpectedTreeHash, 32)) {
    DEBUG((DEBUG_ERROR, "FAIL: owned boot_args / ADT readback\n")); goto Done;
  }
  if (!Sha256HashAll(Seed, sizeof(Seed), Digest)) goto Done;
  for (I = 0; I < 16; I++) { SeedTag[2*I] = Hex[Digest[I] >> 4]; SeedTag[2*I+1] = Hex[Digest[I] & 15]; }
  SeedTag[32] = 0;
  DEBUG((DEBUG_ERROR, "HOST SEED TRANSPORT SHA256 OK\nSEED SHA256[0:16] %a\n", SeedTag));
  DEBUG((DEBUG_ERROR, "BOOT_ARGS PA %lx  BYTES %lx\n", P.Args, (UINT64)sizeof(mHandoffArgs)));
  DEBUG((DEBUG_ERROR, "ADT PA %lx  BYTES %lx\nADT KVA %lx\nTOP PA %lx\n", P.Tree, P.TreeBytes, P.TreeVa, P.Top));
  DEBUG((DEBUG_ERROR, "BOOT_ARGS / ADT VERIFY OK\nHANDOFF DATA PASS - KERNEL JUMP DISABLED\n"));
  DEBUG((DEBUG_ERROR, "MMU/cache/GIC unchanged; UEFI active\nKernel entry transition NOT EXECUTED\n"));
  Status = EFI_SUCCESS;
Done:
  ZeroMem(Seed, sizeof(Seed)); ZeroMem(TreeExpected, sizeof(TreeExpected));
  return Status;
}
