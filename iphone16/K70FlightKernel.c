/* SPDX-License-Identifier: MIT
 * Single boot CPU only. Fixed storage, bounded reads and writes, no scheduler
 * or allocation calls. A fault in a probe must never turn into recursive logging.
 */
#include <kern/thread.h>
#include <machine/machine_routines.h>
#include <kern/K70Flight.h>
#include "K70FlightCore.h"
#include "K70FlightScreen.h"
static struct kf_state k70_flight_state;
static struct kf_screen k70_flight_screen;
static volatile unsigned k70_flight_inside;
extern volatile uint32_t k70_stage;
/* Bounded by-value copies of the origin snapshot. Volatile word stores keep the
 * emergency recorder free of FP/SIMD register usage (no FP context in panic). */
static void kf_copy_orig(struct k70_dw_snapshot *dst, const struct k70_dw_snapshot *src) {
 volatile uint32_t *d=(volatile uint32_t *)dst;
 const volatile uint32_t *s=(const volatile uint32_t *)src;
 for(unsigned i=0;i<sizeof(*dst)/sizeof(uint32_t);i++)d[i]=s[i];
}
static void kf_clear_orig(struct k70_dw_snapshot *dst) {
 volatile uint32_t *d=(volatile uint32_t *)dst;
 for(unsigned i=0;i<sizeof(*dst)/sizeof(uint32_t);i++)d[i]=0;
}

static uint64_t kf_mask(void) {
 uint64_t daif;__asm__ volatile("mrs %0, daif\n\tmsr daifset, #15":"=r"(daif)::"memory");return daif;
}
static void kf_restore(uint64_t daif) {__asm__ volatile("msr daif, %0"::"r"(daif):"memory");}
static int kf_write_probe(uint64_t va,uint64_t *pa,void *ctx) {
 (void)ctx;uint64_t saved,par;
 __asm__ volatile("mrs %0, par_el1\n\tat s1e1w, %2\n\tisb\n\tmrs %1, par_el1\n\tmsr par_el1, %0":"=&r"(saved),"=&r"(par):"r"(va):"memory");
 *pa=(par&UINT64_C(0x000ffffffffff000))|(va&4095);return !(par&1);
}
static int kf_readable(uintptr_t va) {
 uint64_t saved,par;
 if(va<UINT64_C(0xffff000000000000))return 0;
 __asm__ volatile("mrs %0, par_el1\n\tat s1e1r, %2\n\tisb\n\tmrs %1, par_el1\n\tmsr par_el1, %0":"=&r"(saved),"=&r"(par):"r"(va):"memory");
 return !(par&1);
}
static int kf_kernel_pair(uintptr_t fp,uintptr_t *next,uintptr_t *pc,void *ctx) {
 (void)ctx;
 if(!kf_readable(fp) || !kf_readable(fp+15))return 0;
 *next=*(const volatile uintptr_t *)fp;*pc=*(const volatile uintptr_t *)(fp+8);return 1;
}
static void kf_paint(void) {
 (void)kf_screen_draw(&k70_flight_screen,&k70_flight_state,kf_write_probe,0);
 __asm__ volatile("dsb sy":::"memory");
}
void k70_flight_refresh(void) {
 uint64_t mask=kf_mask();
 if(!k70_flight_inside){k70_flight_inside=1;kf_paint();k70_flight_inside=0;}
 kf_restore(mask);
}
unsigned k70_flight_log_height(unsigned fallback) {return k70_flight_screen.bound?k70_flight_screen.top:fallback;}
void k70_flight_bind(uintptr_t va,unsigned w,unsigned h,unsigned stride,unsigned depth) {
 uint64_t mask=kf_mask();
 if(!k70_flight_inside && ml_get_max_cpu_number()==0){
  k70_flight_inside=1;
  (void)kf_screen_bind(&k70_flight_screen,va,0xb8000000,w,h,stride,depth&255,kf_write_probe,0);
  kf_paint();k70_flight_inside=0;
 }
 kf_restore(mask);
}
void k70_flight_begin(void) {
 if(!k70_flight_screen.bound)return;
 uint64_t mask=kf_mask();thread_t self=current_thread();
 if(!k70_flight_inside){k70_flight_inside=1;kf_begin(&k70_flight_state,(uintptr_t)self,thread_get_kernel_stack(self),kernel_stack_size);kf_paint();k70_flight_inside=0;}
 kf_restore(mask);
}
void k70_flight_end(void) {uint64_t mask=kf_mask();k70_flight_state.active=0;kf_restore(mask);}
void k70_flight_allocation(uintptr_t p) {
 uint64_t mask=kf_mask();
 if((uintptr_t)current_thread()==k70_flight_state.target && k70_flight_state.kind!=KF_PANIC){k70_flight_state.allocation=p;k70_flight_state.allocation_seen=1;}
 k70_flight_refresh();kf_restore(mask);
}
void k70_flight_enter(unsigned call,uint64_t arg) {
 uint64_t mask=kf_mask();
 if(!k70_flight_inside){k70_flight_inside=1;kf_enter(&k70_flight_state,(uintptr_t)current_thread(),call,arg);kf_paint();k70_flight_inside=0;}
 kf_restore(mask);
}
void k70_flight_leave(unsigned call,uint64_t result) {
 uint64_t mask=kf_mask();
 if(!k70_flight_inside){k70_flight_inside=1;kf_leave(&k70_flight_state,(uintptr_t)current_thread(),call,result);kf_paint();k70_flight_inside=0;}
 kf_restore(mask);
}

void k70_flight_pmap_assert(uintptr_t caller, uint32_t ppnum, uintptr_t pvh,
    uintptr_t ptep, uintptr_t pmap, enum k70_pmap_owner owner,
    uintptr_t free_caller, uintptr_t va_base_field,
    const struct k70_dw_snapshot *snap)
{
 uint64_t mask = kf_mask();
 struct kf_pmap_assert *record = &k70_flight_state.pmap_assert;
 if (!k70_flight_inside && k70_flight_state.kind != KF_PANIC && !record->pending) {
  record->thread = (uintptr_t)current_thread();
  record->caller = caller;
  record->ppnum = ppnum;
  record->pvh = pvh;
  record->ptep = ptep;
  record->pmap = pmap;
  record->owner = owner;
  record->stage = k70_stage;
  record->free_caller = free_caller;
  if ((va_base_field & 7) == 0 && kf_readable(va_base_field)) {
   uintptr_t base = *(const volatile uintptr_t *)va_base_field;
   record->va = kf_pmap_leaf_va(base, ptep);
  }
  record->va_read = record->va != 0;
  /* An aligned PTE cannot cross a page. Reuse the bounded read probe. */
  record->pte_read = (ptep & 7) == 0 && kf_readable(ptep);
  if (record->pte_read) {
   record->pte = *(const volatile uint64_t *)ptep;
  }
  if (snap) {
   kf_copy_orig(&record->orig, snap);
  } else {
   /* Legacy no-diagnostic entry: publish an explicit UNAVAIL state.
    * Volatile word stores keep adjacent 32-bit fields from merging into one
    * 8-byte SIMD store (no FP/SIMD registers in the emergency recorder). */
   volatile uint32_t *kf_o = (volatile uint32_t *)&record->orig;
   kf_clear_orig(&record->orig);
   kf_o[0] = K70_ORIG_UNAVAIL;   /* status */
   kf_o[1] = K70_R_INVALID_TOK;  /* reason */
  }
  record->orig_published = 1;
  record->pending = 1;
 }
 kf_restore(mask);
}

static int kf_pmap_assert_matches(const char *format, uintptr_t thread,
    const struct kf_pmap_assert *record)
{
 static const char prefix[] = K70_PMAP_ASSERT_PREFIX;
 if (!format || thread != record->thread) {
  return 0;
 }
 for (unsigned i = 0; i < sizeof(prefix) - 1; i++) {
  if (format[i] != prefix[i]) {
   return 0;
  }
 }
 return 1;
}

void k70_flight_panic(const char *format,uintptr_t caller,uintptr_t fp) {
 uint64_t mask=kf_mask();
 struct kf_pmap_assert *record = &k70_flight_state.pmap_assert;
 if (k70_flight_state.kind != KF_PANIC && record->pending &&
     !kf_pmap_assert_matches(format, (uintptr_t)current_thread(), record)) {
  record->pending = 0;
  record->orig_published = 0;
 }
 if(k70_flight_inside){if(k70_flight_state.kind!=KF_PANIC){k70_flight_state.kind=KF_PANIC;k70_flight_state.detail=(uintptr_t)format;k70_flight_state.caller=caller;}else{k70_flight_state.nested++;}k70_flight_state.flags|=KF_REENTRANT;kf_restore(mask);return;}
 if(!k70_flight_inside){k70_flight_inside=1;kf_terminal(&k70_flight_state,KF_PANIC,k70_flight_state.active?(uintptr_t)current_thread():0,(uintptr_t)format,caller,0,fp,kf_kernel_pair,0);kf_paint();k70_flight_inside=0;}
 kf_restore(mask);
}
uintptr_t k70_flight_target_thread(void) { return k70_flight_state.target; }
void k70_flight_wait(uintptr_t thread,uintptr_t event,uint64_t state,uintptr_t caller,uintptr_t fp) {
 /* v18: keep the last blocking site for the heartbeat, regardless of which
  * thread blocks and whether the flight record is active. */
 { extern void k70_wait_note(uintptr_t, uintptr_t, uintptr_t);
   k70_wait_note(thread, event, caller); }
 /* The scheduler call site checks its private TH_WAIT flag before calling. */
 if(!k70_flight_state.active || thread!=k70_flight_state.target)return;
 uint64_t mask=kf_mask();
 if(!k70_flight_inside){k70_flight_inside=1;kf_terminal(&k70_flight_state,KF_WAIT,thread,event,caller,state,fp,kf_kernel_pair,0);kf_paint();k70_flight_inside=0;}
 kf_restore(mask);
}
