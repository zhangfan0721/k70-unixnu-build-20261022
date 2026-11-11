/* Focused host proof for the production recorder and emergency rasterizer. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "K70Flight.h"
#include "K70FlightCore.h"
#include "K70FlightScreen.h"
static uintptr_t frames[32];
static unsigned reads, fail_at;
static const uintptr_t base=UINT64_C(0xfffffff001000000);
static int read_pair(uintptr_t address,uintptr_t *next,uintptr_t *pc,void *ctx) {
 (void)ctx;reads++;
 if(reads==fail_at)return 0;
 assert(address>=base && address+16<=base+sizeof(frames));
 unsigned n=(unsigned)((address-base)/sizeof(uintptr_t));
 *next=frames[n];*pc=frames[n+1];return 1;
}
struct mapping {uintptr_t va;uint64_t pa;int valid;};
static int probe(uint64_t va,uint64_t *pa,void *ctx) {
 struct mapping *m=ctx;if(!m->valid)return 0;
 *pa=m->pa+va-m->va;return 1;
}
int main(void) {
 struct kf_pmap_assert pmap = {
  .caller = UINT64_C(0xfffffff00738bc60), .ppnum = 0x891984,
  .pvh = 2, .ptep = base, .pmap = base + 8, .stage = 12,
  .owner = K70_PMAP_USER, .pte_read = 1,
  .va = UINT64_C(0xfffffff0011a0000), .va_read = 1,
  .free_caller = UINT64_C(0xfffffff007338c58),
 };
 const char *expected[] = {
  "PMAP VA=fffffff0011a0000 PPN=0000000000891984",
  "PMAP F=fffffff007338c58 UP=fffffff00738bc60",
  "PMAP OWNER=USER MAP=fffffff001000008",
  "PMAP PTEP=fffffff001000000 PTE=0000000000000000",
 };
 for (unsigned row = 0; row < 4; row++) {
  struct kf_line line = {0};
  kf_pmap_line(&line, &pmap, row);
  assert(strcmp((const char *)line.data, expected[row]) == 0);
 }
 assert(kf_pmap_leaf_va(base, base + 0xd00) == pmap.va);
 assert(kf_pmap_leaf_va(base + 4096, base + 0xd00) == 0);
 assert(kf_pmap_leaf_va(0, base + 0xd00) == 0);
 assert(kf_pmap_leaf_va(base, base + 0xd01) == 0);
 struct kf_line unavailable_va = {0}, unavailable_f = {0}, unreadable = {0};
 pmap.va_read = 0;
 pmap.free_caller = 0;
 kf_pmap_line(&unavailable_va, &pmap, 0);
 kf_pmap_line(&unavailable_f, &pmap, 1);
 assert(strcmp((const char *)unavailable_va.data,
     "PMAP VA=UNAVAIL PPN=0000000000891984") == 0);
 assert(strcmp((const char *)unavailable_f.data,
     "PMAP F=UNAVAIL UP=fffffff00738bc60") == 0);
 pmap.pte_read = 0;
 kf_pmap_line(&unreadable, &pmap, 3);
 assert(strcmp((const char *)unreadable.data,
     "PMAP PTEP=fffffff001000000 PTE=UNREADABLE") == 0);
 struct kf_state s={0};
 for(unsigned i=0;i<16;i++){frames[i*2]=base+(i+1)*16;frames[i*2+1]=UINT64_C(0xfffffff007000000)+i*4;}
 kf_begin(&s,0x100,base,sizeof(frames));
 kf_enter(&s,0x200,1,0);assert(s.sequence==0);
 kf_enter(&s,0x100,1,0);kf_leave(&s,0x100,1,0);assert(s.calls[0].result==0);
 kf_enter(&s,0x100,3,7);
 kf_terminal(&s,KF_WAIT,0x100,0xabc,0xdef,1,base,read_pair,NULL);
 assert(s.kind==KF_WAIT && s.call==3 && s.detail==0xabc && s.bt_count==12 && (s.flags&KF_TRUNCATED));
 kf_leave(&s,0x100,3,0x1234);assert(s.calls[2].out_sequence>s.terminal_sequence);
 kf_enter(&s,0x100,4,1);assert(s.terminal_call==3 && s.call==4);
 reads=0;fail_at=3;
 kf_terminal(&s,KF_PANIC,0x100,0x5678,0x9876,0,base,read_pair,NULL);
 assert(s.kind==KF_PANIC && s.bt_count==2 && (s.flags&KF_UNREADABLE));
 kf_terminal(&s,KF_WAIT,0x100,1,2,1,base,read_pair,NULL);assert(s.kind==KF_PANIC && s.detail==0x5678);
 struct kf_state bad={0};kf_begin(&bad,0x100,base,sizeof(frames));reads=0;
 kf_terminal(&bad,KF_PANIC,0x100,1,2,0,base+1,read_pair,NULL);assert(reads==0 && (bad.flags&KF_BAD_FRAME));
 kf_begin(&bad,0x100,base,sizeof(frames));reads=0;fail_at=0;frames[0]=base;
 bad.kind=0;kf_terminal(&bad,KF_PANIC,0x100,1,2,0,base,read_pair,NULL);assert(bad.bt_count==1 && (bad.flags&KF_BAD_CHAIN));
 const unsigned width=640,height=800,stride=width*4;
 size_t pixels=(size_t)width*height;
 uint32_t *allocation=malloc((pixels+2)*4);assert(allocation);
 for(size_t i=0;i<pixels+2;i++)allocation[i]=0x12345678;
 struct kf_screen screen={0};struct mapping m={(uintptr_t)(allocation+1),0xb8000000,1};
 assert(kf_screen_bind(&screen,m.va,m.pa,width,height,stride,32,probe,&m));
 unsigned normal_renderer_busy=1;(void)normal_renderer_busy;
 assert(kf_screen_draw(&screen,&s,probe,&m));
 assert(allocation[0]==0x12345678 && allocation[pixels+1]==0x12345678);
 assert(allocation[1]==0x12345678); /* ordinary log area untouched */
 size_t changed=0;for(size_t i=1;i<=pixels;i++)changed+=(allocation[i]!=0x12345678);assert(changed);
 m.valid=0;uint32_t saved=allocation[pixels];assert(!kf_screen_draw(&screen,&s,probe,&m));assert(allocation[pixels]==saved);
 FILE *f=fopen("flight-screen.ppm","wb");assert(f);fprintf(f,"P6\n%u %u\n255\n",width,height);
 for(size_t i=1;i<=pixels;i++){uint32_t v=allocation[i];unsigned char p[3]={(unsigned char)(v>>16),(unsigned char)(v>>8),(unsigned char)v};assert(fwrite(p,1,3,f)==3);}fclose(f);free(allocation);
 puts("PASS: return values, thread filter, wait/resume, panic priority, bounded/failed frame reads, independent guarded framebuffer stores");
}
