// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
// Arm IHI 0062D.c, FaultSetIn (3-113), FSR Format (16-299/300).
// Format[10:9] is not a fault and can be UNKNOWN for a non-translating bank.
// Keep the raw word; never clear FSR or accept any other changed bit here.
static constexpr uint32_t k70FsrFormatMask=0x600U;
static constexpr uint32_t k70FsrFaultMask=~k70FsrFormatMask;
static inline uint32_t k70FsrFaults(uint32_t raw) {return raw&k70FsrFaultMask;}
