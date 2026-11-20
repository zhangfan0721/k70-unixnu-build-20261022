// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef K70_ENTRY_CORE_H
#define K70_ENTRY_CORE_H
#include "MachoCore.h"
typedef int (*K70_READ_PTE)(void *Context, K70_U64 Address, K70_U64 *Value);
typedef struct { K70_U64 Physical, Flags, Level, Raw; } K70_ENTRY_PAGE;
#define K70_ENTRY_WB 1ULL
#define K70_ENTRY_RO 2ULL
#define K70_ENTRY_XP 4ULL
int K70EntryWalk(K70_U64 Tcr, K70_U64 Ttbr, K70_U64 Mair, K70_U64 Va,
                  K70_READ_PTE Read, void *Context, K70_ENTRY_PAGE *Result);
int K70EntryScopes(K70_U64 Base, K70_U64 Capacity, K70_U64 Span,
                    K70_U64 StubBytes, K70_U64 TransitionBytes, K70_U64 Pages[3]);
enum { K70_EXIT_RETURN, K70_EXIT_RETRY, K70_EXIT_ENTER, K70_EXIT_HALT };
int K70ExitDecision(unsigned Attempt, int MapOk, int ExitCode);
int K70EntryCacheProfile(K70_U64 Ctr);
#endif
