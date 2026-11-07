#include "ReadOnlyPolicy.h"
#include "K70Route.h"
static unsigned errors;
static void expect(bool ok){if(!ok)++errors;}
extern "C" unsigned k70_ufs_policy_test() {
 unsigned char c[16]={};
 for(unsigned op=0;op<256;++op){c[0]=op;c[5]=1;c[8]=1;
  expect(K70UfsPolicy::command(0,c,10,2,4096)==(op==0x28));
  expect(!K70UfsPolicy::command(0,c,10,1,4096));}
 for(unsigned i=0;i<16;++i)c[i]=0;
 expect(K70UfsPolicy::command(0,c,6,0,0));c[0]=0x25;
 expect(K70UfsPolicy::command(0,c,10,2,8));
 expect(!K70UfsPolicy::command(1,c,10,2,8));
 expect(!K70UfsPolicy::command(0,c,16,2,8));
 expect(!K70UfsPolicy::range(6,1));expect(!K70UfsPolicy::range(211008,1));
 expect(!K70UfsPolicy::range(2570304,1));expect(!K70UfsPolicy::range(5716032,1));
 expect(!K70UfsPolicy::range(~0ULL,2));expect(!K70UfsPolicy::range(0,~0U));
 expect(K70UfsPolicy::range(0,6));expect(K70UfsPolicy::range(K70UfsPolicy::blocks-5,5));
 expect(!K70UfsPolicy::range(5,2));expect(!K70UfsPolicy::range(K70UfsPolicy::blocks-1,2));
 unsigned char wake[6]={0x1b,0,0,0,0x10,0};
 expect(K70UfsPolicy::command(0xd0,wake,6,0,0));
 for(unsigned byte=0;byte<6;++byte)for(unsigned bit=0;bit<8;++bit) {
   wake[byte]^=1U<<bit;expect(!K70UfsPolicy::command(0xd0,wake,6,0,0));wake[byte]^=1U<<bit;
 }
 K70UfsPolicy::Wake gate;
 expect(!gate.permit(0xd0,wake,6,0,0));expect(!gate.observe(0));
 expect(gate.observe(0x11) && !gate.needed());expect(!gate.permit(0xd0,wake,6,0,0));
 const unsigned powerModes[]={0x22U,0x33U};
 for(unsigned mode:powerModes) {
   gate=K70UfsPolicy::Wake{};expect(gate.observe(mode) && gate.needed());
   expect(gate.permit(0xd0,wake,6,0,0));expect(!gate.permit(0xd0,wake,6,0,0));
   expect(!gate.observe(mode));
 }
 // A declared window widens the readable range without touching the GPT blocks.
 K70UfsPolicy::Window &w=K70UfsPolicy::window();
 expect(!w.declared());expect(!w.inside(211008,1));
 expect(!K70UfsPolicy::range(211008,1));
 expect(w.declare(211008,2359296));
 expect(w.declared() && w.baseLba==211008 && w.blockCount==2359296);
 expect(K70UfsPolicy::range(211008,1));
 expect(K70UfsPolicy::range(211008+2359296-1,1));
 expect(!K70UfsPolicy::range(211008-1,1));
 expect(!K70UfsPolicy::range(211008+2359296,1));
 expect(!K70UfsPolicy::range(211008,2359297));
 expect(!K70UfsPolicy::range(0,6)==false);   // GPT head still readable
 expect(K70UfsPolicy::range(0,6));
 // Declarations that cannot be honoured leave the previous window intact.
 expect(!w.declare(0,0));
 expect(!w.declare(K70UfsPolicy::blocks,1));
 expect(!w.declare(K70UfsPolicy::blocks-5,6));
 expect(w.baseLba==211008 && w.blockCount==2359296);
 w.clear();
 expect(!w.declared() && !K70UfsPolicy::range(211008,1));
 return errors;
}

#ifdef K70_POLICY_MAIN
#include <cstdio>
extern "C" unsigned k70_ufs_route_test();
int main(){
  unsigned e=k70_ufs_policy_test();
  std::printf("k70 policy: %u errors\n",e);
  return e?1:0;
}
#endif
static unsigned regs[0x90000/4];
static unsigned rejection,validSlots,matches,extendedReads;
static unsigned long long lastPair;
static bool same(const char *a,const char *b){while(*a&&*a==*b){++a;++b;}return *a==*b;}
extern "C" unsigned k70_ufs_route_test() {
 regs[0x20/4]=0x4c017e69;regs[0x24/4]=0x60000046;regs[0x28/4]=0x5111;
 // Deliberately use another exclusive slot/bank to catch nuwa constants.
 regs[(0x800+4*7)/4]=0x80000060;regs[(0xc00+4*7)/4]=4;
 regs[(0x1000+4*4)/4]=0x1f000;regs[(0x1800+4*4)/4]=1;
 auto read=[](unsigned n){if(n>=0x800)++extendedReads;return regs[n/4];};
 auto trace=[](const char *s,unsigned long long v){
  if(same(s,"UFS route reject"))rejection=unsigned(v);
  if(same(s,"UFS valid slots"))validSlots=unsigned(v);
  if(same(s,"UFS SID60 matches"))matches=unsigned(v);
  if(same(s,"UFS SMR/S2CR"))lastPair=v;
 };
 unsigned cb=~0U;expect(k70CheckUfsRoute(read,trace,&cb)&&cb==4);
 expect(validSlots==1&&matches==1&&lastPair==0x8000006000000004ULL);
 unsigned modes[]={1,8,9};
 for(unsigned mode: modes) {
  regs[0]=mode;expect(!k70CheckUfsRoute(read,trace,&cb));
  expect(rejection==2&&validSlots==1&&matches==1);
 }
 regs[0]=0;regs[(0x800+4*7)/4]=0;
 expect(!k70CheckUfsRoute(read,trace,&cb));expect(rejection==4&&matches==0);
 regs[(0x800+4*7)/4]=0x80000060;
 regs[0x20/4]^=1;extendedReads=0;expect(!k70CheckUfsRoute(read,trace,&cb));
 expect(rejection==1&&extendedReads==0);regs[0x20/4]^=1;
 regs[0x84000/4]=1;expect(!k70CheckUfsRoute(read,trace,&cb));regs[0x84000/4]=0;
 regs[(0x800+4*8)/4]=0x80000061;regs[(0xc00+4*8)/4]=4;
 expect(!k70CheckUfsRoute(read,trace,&cb));regs[(0x800+4*8)/4]=0;
 regs[(0x800+4*7)/4]=0x80010060;expect(!k70CheckUfsRoute(read,trace,&cb));
 return errors;
}
#ifdef HOST_TEST
int main(){k70_ufs_policy_test();k70_ufs_route_test();return errors?1:0;}
#endif
