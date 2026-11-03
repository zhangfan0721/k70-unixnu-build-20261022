/* SPDX-License-Identifier: MIT */
#ifndef K70_FLIGHT_CORE_H
#define K70_FLIGHT_CORE_H
#include <stdint.h>
#include <stddef.h>
#define KF_FRAMES 12
enum {KF_NONE, KF_WAIT, KF_PANIC};
enum {KF_BAD_FRAME=1, KF_UNREADABLE=2, KF_BAD_CHAIN=4, KF_TRUNCATED=8, KF_BAD_PC=16, KF_REENTRANT=32};
struct kf_call {uint64_t in_sequence,out_sequence,result,argument;};
struct kf_state {
 uintptr_t target,stack_low,stack_high,thread,caller,detail,bt[KF_FRAMES];
 uint64_t sequence,terminal_sequence,wait_state,allocation;
 struct kf_call calls[4];
 unsigned active,call,terminal_call,kind,flags,bt_count,allocation_seen,nested;
};
typedef int (*kf_read_pair)(uintptr_t,uintptr_t *,uintptr_t *,void *);
static inline void kf_begin(struct kf_state *s,uintptr_t thread,uintptr_t low,uintptr_t bytes) {
 if(s->active || s->kind==KF_PANIC || !thread)return;
 s->target=thread;s->active=1;s->stack_low=low;
 s->stack_high=(bytes && bytes<=0x100000 && low<=UINTPTR_MAX-bytes)?low+bytes:0;
}
static inline void kf_enter(struct kf_state *s,uintptr_t thread,unsigned call,uint64_t arg) {
 if(!s->active || thread!=s->target || !call || call>4 || s->kind==KF_PANIC)return;
 s->call=call;s->calls[call-1].in_sequence=++s->sequence;s->calls[call-1].argument=arg;
}
static inline void kf_leave(struct kf_state *s,uintptr_t thread,unsigned call,uint64_t result) {
 if(!s->active || thread!=s->target || !call || call>4 || s->kind==KF_PANIC)return;
 s->calls[call-1].result=result;s->calls[call-1].out_sequence=++s->sequence;
}
static inline void kf_terminal(struct kf_state *s,unsigned kind,uintptr_t thread,uintptr_t detail,
 uintptr_t caller,uint64_t wait_state,uintptr_t fp,kf_read_pair read,void *ctx) {
 if(s->kind==KF_PANIC){if(kind==KF_PANIC)s->nested++;return;}
 if(kind!=KF_PANIC && (!s->active || thread!=s->target))return;
 s->kind=kind;s->thread=thread;s->detail=detail;s->caller=caller;s->wait_state=wait_state;
 s->terminal_call=s->call;
 s->terminal_sequence=++s->sequence;s->bt_count=0;s->flags=0;
 if(thread!=s->target){s->flags=KF_BAD_FRAME;return;}
 for(unsigned n=0;n<KF_FRAMES;n++) {
  uintptr_t next,pc;
  if((fp&15) || fp<s->stack_low || fp>=s->stack_high || s->stack_high-fp<16) {s->flags|=KF_BAD_FRAME;return;}
  if(!read || !read(fp,&next,&pc,ctx)){s->flags|=KF_UNREADABLE;return;}
  s->bt[s->bt_count++]=pc;
  if(pc<UINT64_C(0xffff000000000000)){s->flags|=KF_BAD_PC;return;}
  if(!next)return;
  if(next<=fp){s->flags|=KF_BAD_CHAIN;return;}
  fp=next;
 }
 s->flags|=KF_TRUNCATED;
}
#endif
