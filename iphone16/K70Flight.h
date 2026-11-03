/* SPDX-License-Identifier: MIT */
#ifndef K70_FLIGHT_H
#define K70_FLIGHT_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
void k70_flight_begin(void);
void k70_flight_end(void);
void k70_flight_allocation(uintptr_t);
void k70_flight_enter(unsigned,uint64_t);
void k70_flight_leave(unsigned,uint64_t);
void k70_flight_panic(const char *,uintptr_t,uintptr_t);
void k70_flight_wait(uintptr_t,uintptr_t,uint64_t,uintptr_t,uintptr_t);
void k70_flight_bind(uintptr_t,unsigned,unsigned,unsigned,unsigned);
void k70_flight_refresh(void);
unsigned k70_flight_log_height(unsigned);
#ifdef __cplusplus
}
#endif
#endif
