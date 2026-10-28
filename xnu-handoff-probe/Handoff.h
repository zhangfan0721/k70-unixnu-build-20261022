// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef K70_RUNTIME_HANDOFF_H
#define K70_RUNTIME_HANDOFF_H
#include <Uefi.h>
#include "HandoffCore.h"
EFI_STATUS K70PrepareHandoff(UINT64 Base, UINTN Capacity, UINT64 Span,
                             CONST UINT8 *SeedTrailer, UINTN TrailerBytes);
#endif
