// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef K70_HANDOFF_CORE_H
#define K70_HANDOFF_CORE_H
#include "MachoCore.h"
#define K70_HANDOFF_BASE 0x880004000ULL
#define K70_HANDOFF_WINDOW 0x10000000ULL
#define K70_HANDOFF_SPAN 0x1544000ULL
#define K70_HANDOFF_TREE_BYTES 1724
#define K70_SEED_TRAILER_BYTES 112
typedef struct {
  K70_U64 Base, Capacity, Args, Tree, TreeVa, Top, TreeBytes;
} K70_HANDOFF_LAYOUT;
// Return 1 on success, 0 on rejection. Plan never writes output on rejection.
int K70HandoffPlan(K70_U64 Base, K70_U64 Capacity, K70_U64 Span,
                    K70_U64 TreeBytes, K70_HANDOFF_LAYOUT *Layout);
// Shape/nonzero only: caller MUST additionally verify SHA256(first80)==last32.
int K70SeedMetadata(const K70_U8 *Data, K70_SIZE Size);
int K70CheckBootArgs(const K70_U8 *Data, K70_SIZE Size, const K70_HANDOFF_LAYOUT *Layout);
int K70CheckTree(const K70_U8 *Data, const K70_U8 *Template, K70_SIZE Size,
                  K70_SIZE SeedOffset, const K70_U8 *Seed);
#endif
