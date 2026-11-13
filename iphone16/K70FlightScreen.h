/* SPDX-License-Identifier: MIT */
#ifndef K70_FLIGHT_SCREEN_H
#define K70_FLIGHT_SCREEN_H
#include "K70FlightCore.h"
#include "K70DwOrigin.h"
#include "FramebufferGuard.h"
#include "Font.h"
#define KF_ROWS 25
#define KF_COLS 79
static const uint64_t kf_font[]=GLYPH_FONT;
struct kf_screen {uintptr_t va;uint64_t pa;unsigned width,height,stride,scale,top,cols,bound;};
/* Volatile byte stores prevent constant text copies becoming SIMD accesses. */
struct kf_line {volatile char data[KF_COLS+1];unsigned used;};
static inline void kf_text(struct kf_line *l,const char *s) {
 while(*s && l->used<KF_COLS)l->data[l->used++]=*s++;
 l->data[l->used]=0;
}
static inline void kf_hex(struct kf_line *l,uint64_t v) {
 static const char digits[]="0123456789abcdef";
 for(int n=15;n>=0 && l->used<KF_COLS;n--)l->data[l->used++]=digits[(v>>(n*4))&15];
 l->data[l->used]=0;
}
static inline void kf_hex8(struct kf_line *l,uint64_t v) {
 static const char digits[]="0123456789abcdef";
 for(int n=7;n>=0 && l->used<KF_COLS;n--)l->data[l->used++]=digits[(v>>(n*4))&15];
 l->data[l->used]=0;
}

/* Four fixed rows: VA, the free-list caller, PPN and the owning pmap always
 * share one panel. */
static inline void kf_pmap_line(struct kf_line *line,
    const struct kf_pmap_assert *record, unsigned row)
{
 switch (row) {
 case 0:
  kf_text(line, "PMAP VA=");
  if (record->va_read) { kf_hex(line, record->va); } else { kf_text(line, "UNAVAIL"); }
  kf_text(line, " PPN="); kf_hex(line, record->ppnum);
  break;
 case 1:
  kf_text(line, "PMAP F=");
  if (record->free_caller) { kf_hex(line, record->free_caller); } else { kf_text(line, "UNAVAIL"); }
  kf_text(line, " UP="); kf_hex(line, record->caller);
  break;
 case 2:
  kf_text(line, "PMAP OWNER=");
  kf_text(line, record->owner == K70_PMAP_KERNEL ? "KERNEL" :
      record->owner == K70_PMAP_USER ? "USER" : "UNKNOWN");
  kf_text(line, " MAP="); kf_hex(line, record->pmap);
  break;
 case 3:
  kf_text(line, "PMAP PTEP="); kf_hex(line, record->ptep);
  kf_text(line, " PTE=");
  if (record->pte_read) {
   kf_hex(line, record->pte);
  } else {
   kf_text(line, "UNREADABLE");
  }
  break;
 }
}
/* Defined flag bits of the implemented page-flag set. */
#define KF_FLAGS_DEFINED 0xffu
static inline void kf_orig_line(struct kf_line *line,
    const struct kf_pmap_assert *record, unsigned row)
{
 const struct k70_dw_snapshot *s=&record->orig;
 if(!record->orig_published){kf_text(line,"ORIGv2 UNAVAIL");return;}
 const char *st=s->status==K70_ORIG_HIT?"HIT":s->status==K70_ORIG_OVERFLOW?"OVERFLOW":"UNAVAIL";
 switch(row) {
 case 0:
  kf_text(line,"ORIGv2 ");kf_text(line,st);kf_text(line," E=");kf_hex(line,s->epoch);
  kf_text(line," I=");kf_hex8(line,s->rec.dw_index);kf_text(line," N=");kf_hex8(line,s->dw_count);
  kf_text(line," R=");
  if(s->reason==K70_R_BAD_COUNT){kf_text(line,"BAD_CNT");}else{kf_hex8(line,s->reason);}
  break;
 case 1:
  kf_text(line,"PMAP ORIG DW_CALLER=");kf_hex(line,s->dw_caller);break;
 case 2:
  kf_text(line,"PMAP ORIG OBJ=");kf_hex(line,s->rec.object);
  kf_text(line," OFF=");kf_hex(line,s->rec.offset);break;
 case 3:
  kf_text(line,"PMAP ORIG P=");kf_hex8(line,s->rec.ppn);kf_text(line," D=");kf_hex8(line,s->rec.dw_mask);
  kf_text(line," W=");kf_hex8(line,s->rec.wire_count);kf_text(line," F=");kf_hex8(line,s->rec.flags);
  kf_text(line," K=");kf_hex8(line,s->rec.reserved);break;
 default:
  kf_text(line,"PMAP ORIG BATCH=");kf_hex8(line,s->reserved);
  kf_text(line," UKN=");
  kf_text(line,((KF_FLAGS_DEFINED & ~s->rec.reserved)!=0)?"1":"0");break;
 }
}
static inline int kf_lookup_abort(uint32_t ppn, struct k70_abort_rec *out) {
 return k70_abort_page_get(ppn, out);
}
/* v4: per-page UPL abort context for exactly the page the assertion names. */
static inline void kf_abort_line(struct kf_line *line, unsigned row, uint32_t ppn) {
 /* Static: an automatic aggregate could be zero-initialised with vector
   stores, and this painter must not touch FP/SIMD. One lookup is frozen for
   both rows via kf_abort_cached. */
 static struct k70_abort_rec a;
 static uint32_t cached_ppn;
 static unsigned cached;
 if (!cached || cached_ppn != ppn) {
  cached = kf_lookup_abort(ppn, &a) ? 1u : 2u;
  cached_ppn = ppn;
 }
 if (cached != 1u) {
  kf_text(line, "ABORT RECORD NONE P="); kf_hex8(line, ppn);
  return;
 }
 if (row == 0) {
  kf_text(line, "ABORT CALLER="); kf_hex(line, a.caller);
  kf_text(line, " FL="); kf_hex8(line, a.flags);
 } else {
  kf_text(line, "ABORT ERR="); kf_hex8(line, a.error);
  kf_text(line, " D="); kf_hex8(line, a.dw_mask);
  kf_text(line, " P="); kf_hex8(line, a.ppn);
 }
}
static inline int kf_screen_bind(struct kf_screen *s,uintptr_t va,uint64_t pa,unsigned w,unsigned h,
 unsigned stride,unsigned depth,k70_probe probe,void *ctx) {
 s->bound=0;
 if(!k70_framebuffer_valid(va,pa,w,h,stride,depth,probe,ctx))return 0;
 unsigned scale=w/(6*64);if(!scale)scale=1;if(scale>3)scale=3;
 if(h<KF_ROWS*14*scale)return 0;
 s->va=va;s->pa=pa;s->width=w;s->height=h;s->stride=stride;s->scale=scale;
 s->top=h-KF_ROWS*14*scale;s->cols=w/(6*scale);if(s->cols>KF_COLS)s->cols=KF_COLS;
 s->bound=1;return 1;
}
static inline void kf_cell(struct kf_screen *s,unsigned row,unsigned col,char c) {
 uint64_t glyph=kf_font[(unsigned)(c>=32 && c<=126?c:'?')-32];
 for(unsigned y=0;y<14;y++) {
  unsigned bits=y<6?(unsigned)((glyph>>(32+y*5))&31):y<12?(unsigned)((glyph>>((y-6)*5))&31):0;
  for(unsigned x=0;x<6;x++)for(unsigned dy=0;dy<s->scale;dy++)for(unsigned dx=0;dx<s->scale;dx++) {
   unsigned py=s->top+(row*14+y)*s->scale+dy,px=(col*6+x)*s->scale+dx;
   volatile uint32_t *p=(volatile uint32_t *)(s->va+(uintptr_t)py*s->stride+(uintptr_t)px*4);
   *p=x<5 && ((bits>>x)&1)?0x00ffffff:0x00000000;
  }
 }
}
static inline int kf_screen_draw(struct kf_screen *s,const struct kf_state *r,k70_probe probe,void *ctx) {
 if(!s->bound)return 0;
 uint64_t offset=(uint64_t)s->top*s->stride;
 if(!k70_framebuffer_valid(s->va+offset,s->pa+offset,s->width,KF_ROWS*14*s->scale,s->stride,32,probe,ctx))return 0;
 for(unsigned row=0;row<KF_ROWS;row++) {
  /* The single-CPU reentry guard owns this fixed buffer. Avoid the kernel's
   * automatic stack-zeroing pass emitting SIMD stores for an 80-byte array. */
  static struct kf_line l;l.used=0;l.data[0]=0;
  if(row==0)kf_text(&l,"K70 CAPTURE V1 READY - independent of normal log lock");
  else if(row==1){kf_text(&l,r->kind==KF_PANIC?"PANIC ":r->kind==KF_WAIT?"WAIT ":"NO TERMINAL EVENT ");kf_text(&l,"AT=");kf_hex(&l,r->terminal_call);kf_text(&l," CURRENT=");kf_hex(&l,r->call);kf_text(&l,r->active?" ACTIVE":" INACTIVE");}
  else if(row==2){kf_text(&l,"THREAD=");kf_hex(&l,r->thread);kf_text(&l," TARGET=");kf_hex(&l,r->target);}
  else if(row==3){kf_text(&l,"CALLER=");kf_hex(&l,r->caller);kf_text(&l," DETAIL=");kf_hex(&l,r->detail);}
  else if(row>=4 && row<=7 && r->kind==KF_PANIC && r->pmap_assert.pending){kf_pmap_line(&l,&r->pmap_assert,row-4);}
  else if(row==4){kf_text(&l,"BT_FLAGS=");kf_hex(&l,r->flags);kf_text(&l," WAIT_STATE=");kf_hex(&l,r->wait_state);}
  else if(row>=5 && row<=8){unsigned n=row-5;kf_text(&l,"CALL");char id[2]={(char)('1'+n),0};kf_text(&l,id);kf_text(&l," IN=");kf_hex(&l,r->calls[n].in_sequence);kf_text(&l," OUT=");kf_hex(&l,r->calls[n].out_sequence);kf_text(&l," RET=");kf_hex(&l,r->calls[n].result);}
  else if(row>=9 && row<=14){unsigned n=(row-9)*2;kf_text(&l,"BT ");kf_hex(&l,r->bt_count>n?r->bt[n]:0);kf_text(&l," ");kf_hex(&l,r->bt_count>n+1?r->bt[n+1]:0);}
  else if(row==15){kf_text(&l,"CONTROLLER PTR=");kf_hex(&l,r->allocation);kf_text(&l,r->allocation_seen?" RETURNED":" NOT RETURNED");}
  else if(row==16){kf_text(&l,"1=PARENT 2=VECTORS 3=LOCK 4=MAX_CPUS");}
  else if(row>=18 && row<=22){
   if(r->kind==KF_PANIC && r->pmap_assert.pending)kf_orig_line(&l,&r->pmap_assert,row-18);
  }
  else if(row>=23 && row<=24){if(r->kind==KF_PANIC)kf_abort_line(&l,row-23,r->pmap_assert.ppnum);}
  else if(row==17)kf_text(&l,r->kind==KF_WAIT?(r->terminal_call && r->calls[r->terminal_call-1].out_sequence>r->terminal_sequence?"WAIT recorded, call has since returned":"WAIT recorded, call has not returned yet"):r->kind==KF_PANIC?"PANIC latched before ordinary panic backend":"No panic/wait evidence means inconclusive, not success");
  for(unsigned col=0;col<s->cols;col++)kf_cell(s,row,col,col<l.used?l.data[col]:' ');
 }
 return 1;
}
#endif
