// SPDX-License-Identifier: MIT
static uint8_t k70Gpt[2][24576];
static uint32_t k70le32(const uint8_t *p) {
 return uint32_t(p[0])|(uint32_t(p[1])<<8)|(uint32_t(p[2])<<16)|(uint32_t(p[3])<<24);
}
static uint64_t k70le64(const uint8_t *p) { return k70le32(p)|(uint64_t(k70le32(p+4))<<32); }
static uint32_t k70crc(const uint8_t *p,unsigned n,bool header=false) {
 uint32_t c=~0U;for(unsigned i=0;i<n;++i){c^=header&&i>=16&&i<20?0:p[i];
 for(unsigned b=0;b<8;++b)c=(c>>1)^(0xedb88320U&(0U-(c&1)));}return ~c;
}
static bool k70header(const uint8_t *h,uint64_t self,uint64_t other,uint64_t entries) {
 unsigned n=k70le32(h+12);
 return !memcmp(h,"EFI PART",8)&&k70le32(h+8)==0x10000&&n>=92&&n<=4096&&
   !k70le32(h+20)&&k70le64(h+24)==self&&k70le64(h+32)==other&&
   k70le64(h+72)==entries&&k70le32(h+80)==128&&k70le32(h+84)==128&&
   k70crc(h,n,true)==k70le32(h+16);
}
static void k70hash(const char *label,const uint8_t *p,unsigned size) {
 uint8_t digest[32];SHA256_CTX ctx;SHA256_Init(&ctx);SHA256_Update(&ctx,p,size);SHA256_Final(digest,&ctx);
 boot_progress_stage(label);
 const char *names[]={"UFS SHA 0/4","UFS SHA 1/4","UFS SHA 2/4","UFS SHA 3/4"};
 for(unsigned i=0;i<4;++i){uint64_t v=0;for(unsigned j=0;j<8;++j)v=(v<<8)|digest[8*i+j];
 k70_formal_cpu_trace(names[i],v);}
}
static bool k70qualify() {
 gRootDiagnostic.stage="READ CAPACITY";
 uint8_t cap[8],cdb[10]={0x25};uint32_t scsi=0;
 IOReturn r=hostScsi(0,cdb,10,true,8,1000000,&scsi);
 if(r!=kIOReturnSuccess)return false;
 memcpy(cap,gHost.virt+kDataOffset,8);
 k70_formal_cpu_trace("UFS last LBA",loadBe32(cap));
 k70_formal_cpu_trace("UFS block bytes",loadBe32(cap+4));
 gRootDiagnostic.stage="capacity geometry";
 if(loadBe32(cap)!=K70UfsPolicy::blocks-1||loadBe32(cap+4)!=4096)return false;
 struct Region {uint64_t lba;unsigned count;uint8_t *out;const char *label;};
 Region ranges[]={{0,2,k70Gpt[0],"UFS SHA primary MBR/header"},
 {2,4,k70Gpt[0]+8192,"UFS SHA primary entries"},
 {K70UfsPolicy::blocks-5,4,k70Gpt[1]+8192,"UFS SHA backup entries"},
 {K70UfsPolicy::blocks-1,1,k70Gpt[1],"UFS SHA backup header"}};
 for(auto &v:ranges){
  gRootDiagnostic.stage=v.label;gRootDiagnostic.lba=v.lba;
  k70_formal_cpu_trace("UFS read LBA",v.lba);
  if(hostRead4k(0,v.lba,v.count,v.out)!=kIOReturnSuccess)return false;
  k70hash(v.label,v.out,v.count*4096);
 }
 const uint8_t *a=k70Gpt[0]+4096,*b=k70Gpt[1];
 gRootDiagnostic.stage="GPT header/CRC validation";
 if(!k70header(a,1,K70UfsPolicy::blocks-1,2)||
    !k70header(b,K70UfsPolicy::blocks-1,1,K70UfsPolicy::blocks-5)||
    memcmp(a+40,b+40,32)||memcmp(k70Gpt[0]+8192,k70Gpt[1]+8192,16384)||
    k70crc(k70Gpt[0]+8192,16384)!=k70le32(a+88)||k70le32(a+88)!=k70le32(b+88))return false;
 // Validate every occupied entry and pairwise disjointness in the usable range.
 uint64_t first=k70le64(a+40),last=k70le64(a+48);
 gRootDiagnostic.stage="GPT entry boundaries/disjointness";
 if(first<6||first>last||last>=K70UfsPolicy::blocks-5)return false;
 unsigned used=0;
 for(unsigned i=0;i<128;++i){const uint8_t *e=k70Gpt[0]+8192+128*i;
  uint8_t bits=0;for(unsigned n=0;n<16;++n)bits|=e[n];if(!bits)continue;
  uint64_t lo=k70le64(e+32),hi=k70le64(e+40);
  if(lo<first||lo>hi||hi>last)return false;++used;
  for(unsigned j=0;j<i;++j){const uint8_t *f=k70Gpt[0]+8192+128*j;uint8_t present=0;
   for(unsigned n=0;n<16;++n)present|=f[n];
   if(present&&lo<=k70le64(f+40)&&k70le64(f+32)<=hi)return false;}
 }
 k70_formal_cpu_trace("UFS GPT occupied entries",used);return true;
}
