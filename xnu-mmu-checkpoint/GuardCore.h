// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef K70_GUARD_CORE_H
#define K70_GUARD_CORE_H
#include "MachoCore.h"
int K70DataRange(const void *Map, K70_SIZE Bytes, K70_SIZE Stride, K70_U64 Start, K70_U64 Length);
int K70CpuSupportsXnu(K70_U64 Mmfr0);
#endif
