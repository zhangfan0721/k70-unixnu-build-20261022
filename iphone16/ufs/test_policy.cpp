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
 return errors;
}
static unsigned regs[0x90000/4];
extern "C" unsigned k70_ufs_route_test() {
 regs[0x20/4]=0x4c017e69;regs[0x24/4]=0x60000046;regs[0x28/4]=0x5111;
 // Deliberately use another exclusive slot/bank to catch nuwa constants.
 regs[(0x800+4*7)/4]=0x80000060;regs[(0xc00+4*7)/4]=4;
 regs[(0x1000+4*4)/4]=0x1f000;regs[(0x1800+4*4)/4]=1;
 auto read=[](unsigned n){return regs[n/4];};auto trace=[](const char *,unsigned){};
 unsigned cb=~0U;expect(k70CheckUfsRoute(read,trace,&cb)&&cb==4);
 regs[0x84000/4]=1;expect(!k70CheckUfsRoute(read,trace,&cb));regs[0x84000/4]=0;
 regs[(0x800+4*8)/4]=0x80000061;regs[(0xc00+4*8)/4]=4;
 expect(!k70CheckUfsRoute(read,trace,&cb));regs[(0x800+4*8)/4]=0;
 regs[(0x800+4*7)/4]=0x80010060;expect(!k70CheckUfsRoute(read,trace,&cb));
 return errors;
}
#ifdef HOST_TEST
int main(){k70_ufs_policy_test();k70_ufs_route_test();return errors?1:0;}
#endif
