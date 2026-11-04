// Host fixture for the ACTUAL qualification parser. Never opens a device.
#include <cstdint>
#include <cstring>
#include <cassert>
#include <fstream>
#include <iterator>
#include <vector>
#include <string>
#include <cstdio>
#include <openssl/sha.h>
#include "ReadOnlyPolicy.h"
using IOReturn=unsigned;
static constexpr unsigned kIOReturnSuccess=0,kDataOffset=8192;
static uint8_t dma[16384];
static struct {uint8_t *virt;} gHost={dma};
static std::vector<uint8_t> parts[4];
static unsigned hashes;
static uint32_t loadBe32(const uint8_t *p){return uint32_t(p[0])<<24|uint32_t(p[1])<<16|uint32_t(p[2])<<8|p[3];}
static void boot_progress_stage(const char *){}
static void k70_formal_cpu_trace(const char *s,uint64_t){if(!strncmp(s,"UFS SHA ",8))++hashes;}
static IOReturn hostScsi(unsigned lun,const uint8_t *c,unsigned len,bool dir,unsigned bytes,unsigned,uint32_t *status){
 assert(K70UfsPolicy::command(lun,c,len,dir?2:0,bytes));*status=0;
 uint32_t v=K70UfsPolicy::blocks-1;
 for(unsigned i=0;i<4;++i)dma[kDataOffset+i]=uint8_t(v>>(24-8*i));
 dma[kDataOffset+4]=0;dma[kDataOffset+5]=0;dma[kDataOffset+6]=0x10;dma[kDataOffset+7]=0;
 return 0;
}
static IOReturn hostRead4k(unsigned lun,uint64_t lba,unsigned blocks,void *out){
 assert(!lun&&K70UfsPolicy::range(lba,blocks));
 const uint64_t starts[]={0,2,K70UfsPolicy::blocks-5,K70UfsPolicy::blocks-1};
 for(unsigned i=0;i<4;++i)if(lba==starts[i]){assert(parts[i].size()==blocks*4096);memcpy(out,parts[i].data(),parts[i].size());return 0;}
 assert(false);return 1;
}
#include "Qualification.inc"
static void put32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;++i)p[i]=uint8_t(v>>(8*i));}
static void seal(unsigned headerIndex){unsigned skip=headerIndex?0:4096;auto *h=parts[headerIndex].data()+skip;put32(h+16,k70crc(h,k70le32(h+12),true));}
int main(int argc,char **argv){
 assert(argc==2);
 const char *names[]={"sda-mbr-primary-header.bin","sda-primary-entries.bin","sda-backup-entries.bin","sda-backup-header.bin"};
 for(unsigned i=0;i<4;++i){std::ifstream f(std::string(argv[1])+"/"+names[i],std::ios::binary);assert(f);parts[i]={std::istreambuf_iterator<char>(f),{}};}
 assert(k70qualify());assert(hashes==16);
 auto original=parts[0];parts[0][4096+16]^=1;assert(!k70qualify());parts[0]=original;
 auto backup=parts[3];parts[3][56]^=1;seal(3);assert(!k70qualify());parts[3]=backup;
 auto entries=parts[1];parts[1][127]^=1;assert(!k70qualify());parts[1]=entries;
 // Valid checksums but overlapping used partitions must also be rejected.
 memcpy(parts[1].data()+128+32,parts[1].data()+32,16);parts[2]=parts[1];
 put32(parts[0].data()+4096+88,k70crc(parts[1].data(),16384));
 put32(parts[3].data()+88,k70crc(parts[2].data(),16384));seal(0);seal(3);
 assert(!k70qualify());
 puts("PASS actual qualification parser: recorded GPT and corrupt CRC/GUID/table/overlap cases; no device access");
}
