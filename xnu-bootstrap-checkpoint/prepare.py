#!/usr/bin/env python3
"""Generate stage08 from reviewed stage07 with exact, hash-pinned anchors."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

HERE=Path(__file__).resolve().parent
REVIEWED={
 'blobs.py':'486a1a9c3b534b0f531b6ac4a9484579f9f25ec914051894623a616f778d7be3',
 'prepare.py':'40c8ad04fed1e1e41815bff55f7235ba462c0f61c06714bed6ce9eae4b791412',
 'Entry.c':'85faa1d9659b0fa5e7fbede23142b5d642dae0bc017b71cc537321948d9350de',
 'EntryCore.c':'3a3e0facda7413f3bcf4930dace4d50b88a1a6dec63623954727650811e45ee7',
 'EntryCore.h':'afd74629a9fa7b338f0ecc559bf58262d31527b84d2f447051f6afb817e8bd81',
}
FONT_FILES={
 'Font.h':'d2a3687db67b069f4e34a961e17fd28b0242986e3fa8dd8a7545cab70834fa8e',
 'FrameBuffer.h':'556f0ba7479eda4d0ecfe3a6b01c83ba3cfbfe60338e26d0aeeb8645d615993f',
 'FrameBufferSerialPortLib.c':'07d3b7034159420a074947ccb38db235b95202d9928ed79e367ee770505be61a',
}


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m


def change(text,before,after,count=1):
    if text.count(before)!=count:raise ValueError('Reviewed anchor changed: '+before[:70])
    return text.replace(before,after)


def prepare(root,dtb,kernel,payload,blobs_out):
    old=HERE.parent/'xnu-entry-checkpoint'
    for name,expected in REVIEWED.items():
        if hashlib.sha256((old/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=expected:
            raise ValueError('Reviewed stage07 changed: '+name)
    for name,expected in FONT_FILES.items():
        source=root/'Silicon/Silicium/SiliciumPkg/Library/FrameBufferSerialPortLib'/name
        if hashlib.sha256(source.read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=expected:
            raise ValueError('Pinned framebuffer console changed: '+name)
    if 'PcdFrameBufferFontScale|3' not in (root/'Platforms/Xiaomi/vermeerPkg/vermeer.dsc').read_text():
        raise ValueError('Expected pinned 36-pixel console line profile')
    builder=module('bootstrap_builder',HERE/'blobs.py')
    header,proof=builder.build(kernel,blobs_out)
    previous=module('reviewed_stage07_prepare',old/'prepare.py')
    with tempfile.TemporaryDirectory(prefix='stage07-generator-') as folder:
        report=previous.prepare(root,dtb,kernel,payload,Path(folder)/'previous-blobs')
    app=root/'Platforms/Xiaomi/vermeerProbePkg/Probe'
    text=(app/'Entry.c').read_text()
    text=change(text,'Before[3], Now','Before[4], Now')
    text=change(text,'K70_U64 Pages[3]','K70_U64 Pages[4]')
    text=change(text,'I < 3;','I < 4;',4)
    text=change(text,'Base + 0x3f705c','Base + 0x3f7290',2)
    text=change(text,'Before[1].Flags | Before[2].Flags','Before[1].Flags | Before[2].Flags | Before[3].Flags')
    copy='  CopyMem((VOID *)(UINTN)(Base + 0x3f7290), mEntryStub, sizeof(mEntryStub));'
    check=('  if (sizeof(mEntryVectorPatch) != 64 ||\n'
           '      !Sha256HashAll(mEntryVectorPatch, sizeof(mEntryVectorPatch), Digest) ||\n'
           '      CompareMem(Digest, mEntryVectorPatchHash, 32)) goto Fail;\n'
           '  for (I = 0; I < 16; I++)\n'
           '    if (*(volatile UINT32 *)(UINTN)(Base + 0x3f6000 + I * 128) != 0x14000000) goto Fail;\n')
    patches=('\n  for (I = 0; I < 16; I++)\n'
             '    CopyMem((VOID *)(UINTN)(Base + 0x3f6000 + I * 128), mEntryVectorPatch + 4 * I, 4);\n'
             '  ZeroMem((VOID *)(UINTN)0x881606000ULL, 4096);')
    text=change(text,copy,check+copy+patches)
    anchor='  // Reserve generous slack before changing attributes (splitting page tables may allocate).'
    prefix=('  if (!Sha256HashAll((VOID *)(UINTN)(Base + 0x3f705c), 0x234, Digest) ||\n'
            '      CompareMem(Digest, mOriginalPrefixHash, 32)) goto Fail;\n')
    text=change(text,anchor,prefix+anchor)
    text=change(text,'K70 INSTRUMENTED KERNEL ENTRY CHECKPOINT','K70 STAGE08 ORIGINAL BOOTSTRAP CHECKPOINT')
    text=change(text,'  // Leave at least 384 pixels even for a small 12-pixel console font.',
        '  // Pinned console: (FONT_HEIGHT16-4)*scale3 = 36px. Reset its private cursor,\n'
        '  // then reserve40*36=1440px, strictly below the last diagnostic row1321.\n'
        '  DEBUG((DEBUG_ERROR, "\\f"));')
    text=change(text,'I < 32;','I < 40;')
    text=change(text,'Original __start branch preserved; first-CPU body instrumented','Original __start and firstCPU prefix preserved')
    text=change(text,'No partition writes; no original CPU init or userland','Stop BEFORE common_start TCR/MMU activation; no userland')
    text=change(text,'Blue + white: instrumented kernel-text checkpoint PASS','Blue/white/GREEN: original prefix + bootstrap tables PASS')
    text=change(text,'Red: checkpoint rejected input','Red: exception/contract rejected; hex records below bands')
    anchor='  DEBUG((DEBUG_ERROR, "After checkpoint: Power + VolDown for FASTBOOT\\nPREPARING EXIT BOOT SERVICES\\n"));'
    extra=('  DEBUG((DEBUG_ERROR, "Original prefix hash OK; constructed block maps NOT enabled\\n"));\n'
           '  DEBUG((DEBUG_ERROR, "00 kind,01 cause,02 EL,03 SCTLR,04 VBAR\\n"));\n'
           '  DEBUG((DEBUG_ERROR, "05 ESR,06 ELR,07 FAR,08 SP,09 LR,0A..10 x20..26\\n"));\n'
           '  DEBUG((DEBUG_ERROR, "Block map starts 16KiB before owned RAM; later fix required\\n"));\n')
    text=change(text,anchor,extra+anchor)
    (app/'Entry.c').write_text(text,newline='\n')
    text=(app/'EntryCore.c').read_text()
    text=change(text,'Pages[3]','Pages[4]')
    text=change(text,'StubBytes > 4096 - 0x5c','StubBytes > 4096 - 0x290')
    text=change(text,'Pages[2] = Base + 0x1600000;','Pages[2] = Base + 0x1600000; Pages[3] = Base + 0x3f6000;')
    (app/'EntryCore.c').write_text(text,newline='\n')
    text=(app/'EntryCore.h').read_text()
    text=change(text,'Pages[3]','Pages[4]')
    (app/'EntryCore.h').write_text(text,newline='\n')
    (app/'EntryBlobs.h').write_text(header,newline='\n')
    text=(app/'Preflight.c').read_text()
    text=change(text,'K70 INSTRUMENTED ENTRY - DATA PREFLIGHT','K70 STAGE08 BOOTSTRAP - DATA PREFLIGHT')
    (app/'Preflight.c').write_text(text,newline='\n')
    report.update(mode='original-prefix-bootstrap-checkpoint',entry=proof,
                  original_first_cpu_prefix_preserved=True,original_cpu_init_completed=False,
                  original_common_start_executed=False,hardware_tested=False)
    report['display']=dict(console_row_pixels=36,spacer_lines=40,context_start_row=1440,
                           record_last_row=1321,console_cursor_explicitly_reset=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['uefi','dtb','kernel','payload','blobs']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    try:r=prepare(a.uefi.resolve(),a.dtb.resolve(),a.kernel.resolve(),a.payload.resolve(),a.blobs.resolve())
    except (ValueError,OSError) as e:p.exit(1,str(e)+'\n')
    print(json.dumps(r,indent=2))

