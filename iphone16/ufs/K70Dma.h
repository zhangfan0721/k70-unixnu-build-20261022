// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
// Software descriptor validation, NOT hardware DMA isolation.
static bool k70DmaRange(uint64_t base, uint64_t bytes, uint64_t at, uint64_t length) {
    return length && at>=base && at-base<bytes && length<=bytes-(at-base);
}
static bool k70DmaAllocation(uint64_t base,uint64_t contiguous,uint64_t limit) {
    return base && !(base&4095) && contiguous>=kDmaBytes && base<limit && kDmaBytes<=limit-base;
}
static bool k70DmaDescriptors(uint64_t base,uint64_t limit,unsigned direction,unsigned bytes,
                              const uint32_t *u,const uint32_t *prd) {
    if(!k70DmaAllocation(base,kDmaBytes,limit) || bytes>kDataMax || (bytes&3) ||
       (bytes?direction!=2:direction!=0))return false;
    uint64_t command=uint64_t(u[4])|(uint64_t(u[5])<<32);
    if(command!=base+kUcdOffset || u[0]!=(0x10000000U|(direction<<25)) || u[1] ||
       u[2]!=15 || u[3] || u[6]!=((512U>>2)|((kRspOffset>>2)<<16)) ||
       u[7]!=((bytes?1U:0U)|((kPrdtOffset>>2)<<16)))return false;
    if(!k70DmaRange(base,kDmaBytes,base,32) ||
       !k70DmaRange(base,kDmaBytes,command,32) ||
       !k70DmaRange(base,kDmaBytes,command+kRspOffset,512) ||
       !k70DmaRange(base,kDmaBytes,command+kPrdtOffset,16))return false;
    if(!bytes)return true;
    uint64_t data=uint64_t(prd[0])|(uint64_t(prd[1])<<32);
    return data==base+kDataOffset && prd[2]==0 && prd[3]==bytes-1 &&
           k70DmaRange(base,kDmaBytes,data,bytes);
}
