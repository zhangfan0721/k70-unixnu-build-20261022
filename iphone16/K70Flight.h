/* SPDX-License-Identifier: MIT */
#ifndef K70_FLIGHT_H
#define K70_FLIGHT_H
#include <stdint.h>
#define K70_PMAP_ASSERT_PREFIX "%s: Found at least one mapping to "
enum k70_pmap_owner { K70_PMAP_UNKNOWN, K70_PMAP_KERNEL, K70_PMAP_USER };
#ifdef __cplusplus
extern "C" {
#endif
void k70_flight_begin(void);
void k70_flight_end(void);
void k70_flight_allocation(uintptr_t);
void k70_flight_enter(unsigned,uint64_t);
void k70_flight_leave(unsigned,uint64_t);
void k70_flight_panic(const char *,uintptr_t,uintptr_t);
void k70_flight_pmap_assert(uintptr_t caller, uint32_t ppnum, uintptr_t pvh,
    uintptr_t ptep, uintptr_t pmap, enum k70_pmap_owner owner);
void k70_flight_wait(uintptr_t,uintptr_t,uint64_t,uintptr_t,uintptr_t);
void k70_flight_bind(uintptr_t,unsigned,unsigned,unsigned,unsigned);
void k70_flight_refresh(void);
unsigned k70_flight_log_height(unsigned);
#ifdef __cplusplus
}
#endif
#endif
