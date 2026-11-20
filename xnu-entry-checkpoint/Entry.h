// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef K70_ENTRY_H
#define K70_ENTRY_H
#include <Uefi.h>
EFI_STATUS K70EntryCheckpoint(EFI_HANDLE ImageHandle, UINT64 Base, UINTN Capacity, UINT64 Span);
#endif

