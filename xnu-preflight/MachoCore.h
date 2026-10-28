// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef K70_MACHO_CORE_H
#define K70_MACHO_CORE_H
#ifdef K70_HOST
#include <stdint.h>
#include <stddef.h>
typedef uint8_t K70_U8;
typedef uint32_t K70_U32;
typedef uint64_t K70_U64;
typedef size_t K70_SIZE;
#else
#include <Base.h>
typedef UINT8 K70_U8;
typedef UINT32 K70_U32;
typedef UINT64 K70_U64;
typedef UINTN K70_SIZE;
#endif

#define K70_MAX_BYTES (64ULL * 1024 * 1024)
#define K70_MAX_SEGMENTS 32
enum { K70_OK, K70_BAD_HEADER, K70_BAD_COMMAND, K70_BAD_SEGMENT,
       K70_BAD_ENTRY, K70_NO_SPACE, K70_UNSUPPORTED, K70_BAD_PAYLOAD };

typedef struct {
  K70_U64 Offset, Size, FileOffset, FileSize;
  K70_U32 Protection;
  char Name[17];
} K70_SEGMENT;

typedef struct {
  K70_U64 VmBase, Span, EntryOffset;
  K70_U32 Count;
  K70_SEGMENT Segments[K70_MAX_SEGMENTS];
} K70_PLAN;

int K70ParseMachO(const K70_U8 *Data, K70_SIZE Size, K70_PLAN *Plan);
int K70LoadMachO(const K70_U8 *Data, K70_SIZE Size, K70_U8 *Destination,
                 K70_SIZE Capacity, K70_PLAN *Plan);
int K70Place(const K70_PLAN *Plan, K70_U64 Base, K70_U64 Limit, K70_U64 *Entry);
int K70RangeInReserved(K70_U64 Base, K70_U64 Size);
// Checks envelope metadata, not the body digest. Caller must hash the body
// and materialized image against its independently pinned expected digests.
int K70InspectPayload(const K70_U8 *Data, K70_SIZE Size,
                       const K70_U8 *KernelHash, const K70_U8 *MappedHash,
                       K70_PLAN *Plan);
#endif
