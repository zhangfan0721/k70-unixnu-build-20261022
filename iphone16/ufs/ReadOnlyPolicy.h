// SPDX-License-Identifier: MIT
#pragma once
// This candidate is bound to the recorded K70 LUN0 geometry (4KiB sectors).
// Only GPT blocks are readable. In particular, no old-super, super or userdata
// contents can be addressed, and no device-to-host request has a general range.
namespace K70UfsPolicy {
static constexpr unsigned long long blocks = 61842432ULL;
static inline bool range(unsigned long long lba, unsigned count) {
    if (!count || lba >= blocks || count > blocks-lba) return false;
    return (lba < 6 && count <= 6-lba) ||
           (lba >= blocks-5 && count <= blocks-lba);
}
static inline bool command(unsigned lun, const unsigned char *cdb,
                           unsigned length, unsigned direction, unsigned bytes) {
    if (!cdb || direction == 1) return false;
    // One exact ACTIVE wake is separately gated by a successful power query
    // and a one-shot token in the integrated startup path. No data-out payload.
    if(lun==0xd0) {
        return length==6 && direction==0 && bytes==0 && cdb[0]==0x1b &&
            cdb[1]==0 && cdb[2]==0 && cdb[3]==0 && cdb[4]==0x10 && cdb[5]==0;
    }
    if(lun)return false;
    if (length == 6 && cdb[0] == 0) {
        if (direction || bytes) return false;
        for (unsigned i=1;i<6;++i) if (cdb[i]) return false;
        return true;
    }
    if (length != 10 || direction != 2) return false;
    if (cdb[0] == 0x25) {
        if (bytes != 8) return false;
        for (unsigned i=1;i<10;++i) if(cdb[i]) return false;
        return true;
    }
    if (cdb[0] != 0x28 || cdb[1] || cdb[6] || cdb[9]) return false;
    unsigned long long lba = (static_cast<unsigned long long>(cdb[2])<<24) |
        (unsigned(cdb[3])<<16) | (unsigned(cdb[4])<<8) | cdb[5];
    unsigned count = (unsigned(cdb[7])<<8) | cdb[8];
    return count && count <= 32 && bytes == count*4096 && range(lba,count);
}
struct Wake {
    unsigned mode=0;
    bool queried=false,attempted=false;
    bool observe(unsigned value) {
        if(queried || (value!=0x11 && value!=0x22 && value!=0x33))return false;
        mode=value;queried=true;return true;
    }
    bool needed() const {return queried && (mode==0x22 || mode==0x33);}
    bool permit(unsigned lun,const unsigned char *cdb,unsigned length,
                unsigned direction,unsigned bytes) {
        if(!command(lun,cdb,length,direction,bytes))return false;
        if(lun!=0xd0)return true;
        if(!needed() || attempted)return false;
        attempted=true;return true;
    }
};
}
