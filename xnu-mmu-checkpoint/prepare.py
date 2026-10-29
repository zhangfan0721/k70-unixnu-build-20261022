#!/usr/bin/env python3
"""Generate stage09 from hash-pinned stage08 without mutating earlier sources."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

HERE=Path(__file__).resolve().parent


def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def change(text,before,after,count=1):
    if text.count(before)!=count:raise ValueError('Reviewed anchor changed: '+before[:80])
    return text.replace(before,after)


def prepare(root,dtb,kernel,payload,blobs_out):
    old=HERE.parent/'xnu-bootstrap-checkpoint'
    for name,digest in {'prepare.py':'e2a7a103dd0dda7ec69e18eac060114c9d24be9b7a745e28817b3fb8d9d39673',
        'blobs.py':'b8417450f7401d7839feb573206c494b0a91a49f5d6bcdf0fe63c845ce466065',
        'checkpoint.S':'9a6788f1a637fc2457d00ccbca2d1aa77c63f76e11d07c0c34d31fcec41678bd',
        'transition.S':'595977ad2f19b25a25774f589771f52f78befb531c93e76eada317b9f019030f'}.items():
        if hashlib.sha256((old/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=digest:raise ValueError('Reviewed stage08 changed: '+name)
    previous=module('mmu_previous_prepare',old/'prepare.py')
    # The previous generator validates font/kernel inputs before creating outputs.
    with tempfile.TemporaryDirectory(prefix='stage08-generator-') as tmp:
        report=previous.prepare(root,dtb,kernel,payload,Path(tmp)/'blobs')
    builder=module('mmu_builder',HERE/'blobs.py');header,proof=builder.build(kernel,blobs_out)
    app=root/'Platforms/Xiaomi/vermeerProbePkg/Probe'
    text=(app/'Entry.c').read_text()
    text=change(text,'#include "EntryBlobs.h"','#include "EntryBlobs.h"\n#include "GuardCore.h"')
    anchor='STATIC UINT64 Attributes(UINT64 Flags) {'
    guard='''STATIC BOOLEAN K70GuardReady(CONST K70_REGS *Regs, UINT64 Guard) {
  EFI_GCD_MEMORY_SPACE_DESCRIPTOR Region;
  K70_ENTRY_PAGE Page;
  UINT64 Address;
  if (Guard != 0x880000000ULL) return FALSE;
  for (Address = Guard; Address < Guard + 16384; Address += 4096) {
    if (EFI_ERROR(gDS->GetMemorySpaceDescriptor(Address, &Region)) ||
        Region.GcdMemoryType != EfiGcdMemoryTypeSystemMemory || Region.BaseAddress > Address ||
        Region.Length < 4096 || Address - Region.BaseAddress > Region.Length - 4096 ||
        !PageInfo(Regs, Address, &Page) || (Page.Flags & K70_ENTRY_RO)) return FALSE;
  }
  return TRUE;
}
'''
    text=change(text,anchor,guard+anchor)
    text=change(text,'UINTN Capacity, UINT64 Span) {','UINTN Capacity, UINT64 Span, UINT64 Guard) {')
    text=change(text,'Before[4]','Before[6]');text=change(text,'K70_U64 Pages[4]','K70_U64 Pages[6]')
    text=change(text,'I < 4;','I < 6;',4)
    text=change(text,'UINT64 El, Sctlr, Ctr, Daif','UINT64 El, Sctlr, Ctr, Mmfr0, Daif')
    anchor='  if (El != 4 || (Sctlr & 0x1005) != 0x1005 ||'
    text=change(text,anchor,'  __asm__ volatile("mrs %0, id_aa64mmfr0_el1" : "=r"(Mmfr0));\n'+anchor+'\n      !K70CpuSupportsXnu(Mmfr0) || Guard != 0x880000000ULL ||')
    text=change(text,'  if (!Identity(0xb8000000ULL)', '  if (!K70GuardReady(&Regs, Guard)) goto Fail;\n  if (!Identity(0xb8000000ULL)')
    text=change(text,'Before[1].Flags | Before[2].Flags | Before[3].Flags','Before[1].Flags | Before[2].Flags | Before[3].Flags | Before[5].Flags')
    anchor='  if (CompareMem((VOID *)(UINTN)(Base + 0x3f7290), mEntryOriginalPatch'
    text=change(text,anchor,'  ZeroMem((VOID *)(UINTN)0x881608000ULL, 4096);\n'+anchor)
    text=change(text,'Base + 0x3f7290','Base + 0x1604000',2)
    anchor='  CopyMem((VOID *)(UINTN)(Base + 0x1604000), mEntryStub, sizeof(mEntryStub));'
    extra='''  if (sizeof(mMmuCodePatches) != 12 || sizeof(mMmuCodeOriginals) != 12 ||
      !Sha256HashAll(mMmuCodePatches, sizeof(mMmuCodePatches), Digest) ||
      CompareMem(Digest, mMmuCodePatchesHash, 32)) goto Fail;
  for (I = 0; I < 3; I++)
    if (CompareMem((VOID *)(UINTN)(Base + mMmuCodeOffsets[I]), mMmuCodeOriginals + 4 * I, 4)) goto Fail;
  for (I = 0; I < 3; I++)
    CopyMem((VOID *)(UINTN)(Base + mMmuCodeOffsets[I]), mMmuCodePatches + 4 * I, 4);
'''
    text=change(text,anchor,extra+anchor)
    anchor='  // Reserve generous slack before changing attributes (splitting page tables may allocate).'
    extra='''  if (!Sha256HashAll((VOID *)(UINTN)0x881608000ULL, sizeof(mEntryStub), Digest) ||
      CompareMem(Digest, mEntryStubHash, 32) ||
      !Sha256HashAll((VOID *)(UINTN)(Base + 0x3fb2fc), 16, Digest) ||
      CompareMem(Digest, mOriginalHelperHash, 32)) goto Fail;
'''
    text=change(text,anchor,extra+anchor)
    anchor='  if (Map == NULL) { Status = EFI_OUT_OF_RESOURCES; goto Fail; }'
    receipt='''
  MapBytes = MapCapacity;
  Status = gBS->GetMemoryMap(&MapBytes, Map, &Key, &DescriptorBytes, &DescriptorVersion);
  if (EFI_ERROR(Status) || !K70DataRange(Map, MapBytes, DescriptorBytes, Guard, Capacity + 16384)) goto Fail;'''
    text=change(text,anchor,anchor+receipt)
    text=change(text,'    if (EFI_ERROR(Status)) {','    if (EFI_ERROR(Status) || !K70DataRange(Map, MapBytes, DescriptorBytes, Guard, Capacity + 16384)) {')
    text=change(text,'K70 STAGE08 ORIGINAL BOOTSTRAP CHECKPOINT','K70 STAGE09 ORIGINAL MMU CHECKPOINT')
    text=change(text,'Stop BEFORE common_start TCR/MMU activation; no userland','Test original TCR/MMU enable; stop before arm_init; no userland')
    text=change(text,'Blue/white/GREEN: original prefix + bootstrap tables PASS','Blue/white/GREEN/CYAN: XNU mappings, aliases and stack PASS')
    text=change(text,'Original prefix hash OK; constructed block maps NOT enabled','Original prefix/helper hashes OK; original MMU sequence follows')
    text=change(text,'Block map starts 16KiB before owned RAM; later fix required','Guard16KiB owned; tail16KiB unmapped: AT only, no data access')
    anchor='  DEBUG((DEBUG_ERROR, "After checkpoint: Power + VolDown for FASTBOOT\\nPREPARING EXIT BOOT SERVICES\\n"));'
    text=change(text,anchor,'  DEBUG((DEBUG_ERROR, "11 TCR,12 TTBR0,13 TTBR1,14 MAIR; 15..1B PARs\\n1C alias-word,1D stack-test; 00=0 + CYAN means checkpoint PASS\\n"));\n'+anchor)
    text=change(text,'strictly below the last diagnostic row1321','strictly below the last diagnostic row1270')
    (app/'Entry.c').write_text(text,newline='\n')
    text=(app/'Entry.h').read_text();text=change(text,'UINT64 Span);','UINT64 Span, UINT64 Guard);');(app/'Entry.h').write_text(text,newline='\n')
    text=(app/'EntryCore.c').read_text();text=change(text,'Pages[4]','Pages[6]')
    text=change(text,'StubBytes > 4096 - 0x290','StubBytes > 4096')
    text=change(text,'Pages[3] = Base + 0x3f6000;','Pages[3] = Base + 0x3f6000;\n  Pages[4] = Base + 0x3fb000; Pages[5] = Base + 0x1604000;')
    (app/'EntryCore.c').write_text(text,newline='\n')
    text=(app/'EntryCore.h').read_text();text=change(text,'Pages[4]','Pages[6]');(app/'EntryCore.h').write_text(text,newline='\n')
    (app/'EntryBlobs.h').write_text(header,newline='\n')
    for name in ['GuardCore.c','GuardCore.h']:shutil.copy2(HERE/name,app/name)
    text=(app/'VermeerProbe.inf').read_text();text=change(text,'  EntryBlobs.h','  EntryBlobs.h\n  GuardCore.c\n  GuardCore.h');(app/'VermeerProbe.inf').write_text(text,newline='\n')
    text=(app/'Preflight.c').read_text()
    text=change(text,'Destination = 0x880004000ULL;','Destination = 0x880004000ULL, Prefix = 0x880000000ULL;')
    text=change(text,'BOOLEAN Allocated = FALSE;','BOOLEAN Allocated = FALSE, PrefixAllocated = FALSE;')
    anchor='  Status = gBS->AllocatePages(AllocateAddress, EfiLoaderData, Pages, &Destination);'
    extra='''  Status = gBS->AllocatePages(AllocateAddress, EfiLoaderData, 4, &Prefix);
  DEBUG((DEBUG_ERROR, "PREFIX GUARD %lx + 4000: %r\\n", Prefix, Status));
  if (EFI_ERROR(Status)) goto Wait;
  PrefixAllocated = TRUE; Status = EFI_ABORTED;
  if (Prefix != 0x880000000ULL) goto Wait;
  ZeroMem((VOID *)(UINTN)Prefix, 16384);
'''
    text=change(text,anchor,extra+anchor)
    text=change(text,'EFI_PAGES_TO_SIZE(Pages), Plan.Span);','EFI_PAGES_TO_SIZE(Pages), Plan.Span, Prefix);')
    anchor='  if (Allocated) gBS->FreePages(Destination, Pages);'
    text=change(text,anchor,anchor+'\n  if (PrefixAllocated) gBS->FreePages(Prefix, 4);')
    text=change(text,'K70 STAGE08 BOOTSTRAP - DATA PREFLIGHT','K70 STAGE09 MMU - DATA PREFLIGHT')
    (app/'Preflight.c').write_text(text,newline='\n')
    report.update(mode='original-common-mmu-checkpoint',entry=proof,guard_separately_allocated=True,
        guard_descriptor_receipt_required=True,original_common_start_instrumented=True,original_common_start_executed=False,
        original_cpu_init_completed=False,hardware_tested=False)
    report['display']=dict(console_row_pixels=36,spacer_lines=40,context_start_row=1440,record_last_row=1270,columns=2,console_cursor_explicitly_reset=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['uefi','dtb','kernel','payload','blobs']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    try:r=prepare(a.uefi.resolve(),a.dtb.resolve(),a.kernel.resolve(),a.payload.resolve(),a.blobs.resolve())
    except (ValueError,OSError) as e:p.exit(1,str(e)+'\n')
    print(json.dumps(r,indent=2))
