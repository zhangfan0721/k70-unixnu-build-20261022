"""Conservative fixed-profile software model; never a hardware translation claim."""
POOL=0x88017a000
TCR=0x22a51a251a
MAIR=0x0c0804ff00bb44ff
PA_MASK=((1<<40)-1)&~4095


def guard_layout(base,capacity,guard,guard_bytes):
    if (base,capacity,guard,guard_bytes)!=(0x880004000,0x10000000,0x880000000,0x4000):
        raise ValueError('Not the reviewed owned guard/window profile')
    return dict(owned_start=guard,owned_end=base+capacity,mapped_start=guard,
                mapped_end=0x890000000,unmapped_tail_bytes=0x4000,maps_contained=True)


def walk(va,regs,read,*,write=False,execute=False):
    if type(va) is not int or not 0<=va<(1<<64):return None
    if any(regs.get(k)!=v for k,v in [('tcr',TCR),('ttbr0',POOL),('ttbr1',POOL+4096),('mair',MAIR)]):
        return None
    if va>=(1<<64)-(1<<38):
        root=regs['ttbr1'];low=va&((1<<38)-1)
    else:
        low=va&((1<<56)-1) # The pinned TCR enables TBI0 only.
        if low>=(1<<38):return None
        root=regs['ttbr0']
    def get(at):
        if at&7 or not POOL<=at<=POOL+65536-8:return None
        return read(at)
    descriptor=get(root+8*((low>>30)&255))
    if descriptor is None or descriptor&3!=3:return None
    child=descriptor&PA_MASK
    if descriptor!=(child|3) or not POOL<=child<=POOL+65536-4096:return None
    leaf=get(child+8*((low>>21)&511))
    if leaf is None or leaf&3!=1:return None
    address=leaf&PA_MASK
    flags=leaf&~PA_MASK
    if address&0x1fffff or flags&~(0x601|0x80|(3<<53)) or flags&0x601!=0x601:return None
    if write and leaf&0x80:return None
    if execute and (leaf&(1<<53) or (regs.get('sctlr',0)&(1<<19) and not leaf&0x80)):
        return None
    physical=address|(low&0x1fffff)
    if not 0x880000000<=physical<0x890000000:return None
    return physical

