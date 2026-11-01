"""Assemble and verify a public, zero-identity formal-chain template. No device I/O."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import lzma
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid

HERE=Path(__file__).resolve().parent


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


handoff=module('formal_handoff',HERE.parent/'xnu-handoff/handoff.py')


def blank_identity(blob):
    tree=handoff.parse_tree(blob)
    chosen=tree.get('/chosen',{})
    result=bytearray(blob)
    offset=None
    for key,length in [('unique-chip-id',8),('random-seed',64)]:
        if len(chosen.get(key,b''))!=length:
            raise ValueError('Expected /chosen/'+key+' with declared length')
        marker=key.encode().ljust(32,b'\0')+struct.pack('<I',length)
        if blob.count(marker)!=1:
            raise ValueError('Ambiguous private seed field')
        at=blob.index(marker)+len(marker)
        result[at:at+length]=bytes(length)
        if key=='unique-chip-id': offset=at
    parsed=handoff.parse_tree(result)['/chosen']
    if parsed['unique-chip-id']!=bytes(8) or parsed['random-seed']!=bytes(64):
        raise ValueError('Seed blanking failed')
    return bytes(result),offset


def boot_v0_id(image):
    if len(image)<4096 or image[:8]!=b'ANDROID!':
        raise ValueError('Invalid Android header')
    ks,_,rs,_,ss,_,_,page,version,_=struct.unpack_from('<10I',image,8)
    if page!=4096 or version!=0 or ss or not ks or not rs:
        raise ValueError('Unsupported Android boot layout')
    start=page*(1+(ks+page-1)//page)
    if start+rs>len(image): raise ValueError('Truncated Android payload')
    digest=hashlib.sha1()
    for data in (image[page:page+ks],image[start:start+rs],b''):
        digest.update(data);digest.update(struct.pack('<I',len(data)))
    return digest.digest()+bytes(12)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(*args,**kwargs):
    return subprocess.run([str(a) for a in args],check=True,**kwargs)


def verify_fd_fv(fd,expected):
    """Bind the checked FV to the actual FD's LZMA-guided FV_IMAGE file."""
    if len(fd)<72 or fd[40:44]!=b'_FVH':
        raise ValueError('FD does not start with its compact firmware volume')
    limit=struct.unpack_from('<Q',fd,32)[0]
    header=struct.unpack_from('<H',fd,48)[0]
    ext=struct.unpack_from('<H',fd,52)[0]
    if ext:
        if ext+20>limit: raise ValueError('Invalid compact FV extension')
        header=max(header,ext+struct.unpack_from('<I',fd,ext+16)[0])
    if not 56<=header<=limit<=len(fd): raise ValueError('Invalid compact FV bounds')
    def sections(blob,start,end):
        while start+4<=end:
            count=int.from_bytes(blob[start:start+3],'little');hs=4
            if count==0xffffff:
                if start+8>end: raise ValueError('Truncated extended section')
                count=struct.unpack_from('<I',blob,start+4)[0];hs=8
            if count<hs or start+count>end: raise ValueError('Invalid firmware section')
            yield blob[start+3],blob[start:start+count],hs
            start+=(count+3)&~3
    at=(header+7)&~7
    matches=0
    lzma_guid=uuid.UUID('EE4E5898-3914-4259-9D6E-DC7BD79403CF').bytes_le
    while at+24<=limit and fd[at:at+24]!=b'\xff'*24:
        size=int.from_bytes(fd[at+20:at+23],'little');hs=24
        if size==0xffffff:
            if at+32>limit: raise ValueError('Truncated extended FFS')
            size=struct.unpack_from('<Q',fd,at+24)[0];hs=32
        if size<hs or at+size>limit: raise ValueError('Invalid compact FFS bounds')
        if fd[at+18]==0x0b: # EFI_FV_FILETYPE_FIRMWARE_VOLUME_IMAGE
            for kind,section,sh in sections(fd,at+hs,at+size):
                if kind!=2 or section[sh:sh+16]!=lzma_guid: continue
                if len(section)<sh+20: raise ValueError('Truncated GUID section')
                data_at=struct.unpack_from('<H',section,sh+16)[0]
                if not sh+20<=data_at<len(section): raise ValueError('Invalid guided data offset')
                decoder=lzma.LZMADecompressor(format=lzma.FORMAT_ALONE,memlimit=64<<20)
                unpacked=decoder.decompress(section[data_at:],max_length=64<<20)
                if not decoder.eof: raise ValueError('Incomplete or oversized LZMA firmware volume')
                for nested_kind,nested,nh in sections(unpacked,0,len(unpacked)):
                    if nested_kind==0x17 and nested[nh:]==expected:
                        matches+=1
        at=(at+size+7)&~7
    if matches!=1:
        raise ValueError('Final FD does not contain exactly the verified FVMAIN')
    return True


def verify_firmware(uefi,fd):
    verifier=module('formal_fv',HERE.parent/'uefi-probe/verify_fv.py')
    root=uefi/'Build/vermeerFormalPkg'
    volumes=list(root.rglob('FVMAIN.Fv'))
    if len(volumes)!=1:
        raise ValueError('Expected exactly one FVMAIN volume')
    fv=volumes[0].read_bytes()
    verify_fd_fv(fd.read_bytes(),fv)
    records={}
    for name,guid,kind in [
        ('UniXNU','9B665204-A133-47A2-9396-9E2B370A4E25',9),
        ('UniXNUDxe','29B950CF-586D-49EA-9D71-F88645CCDAF6',7),
        ('DarwinBoot','1B64AF87-8415-4B57-9B16-680D70913B9F',7),
        ('UniXNURamDiskDxe','75CA63AD-FBAE-4A06-92A0-F937C671251D',7)]:
        embedded=verifier.probe_pe(fv,uuid.UUID(guid).bytes_le,kind)
        candidates=list(root.rglob(name+'.efi'))
        digest=hashlib.sha256(embedded).hexdigest()
        if not candidates or digest not in {sha(p) for p in candidates}:
            raise ValueError('Embedded firmware module differs from build: '+name)
        if embedded[:2]!=b'MZ':
            raise ValueError('Expected a PE module: '+name)
        pe=struct.unpack_from('<I',embedded,0x3c)[0]
        if embedded[pe:pe+4]!=b'PE\0\0' or struct.unpack_from('<H',embedded,pe+4)[0]!=0xaa64:
            raise ValueError('Expected AArch64 PE: '+name)
        records[name]={'guid':guid,'sha256':digest}
    return {'fd_sha256':sha(fd),'fvmain_sha256':sha(volumes[0]),'embedded_modules':records}


def build(args):
    out=args.out.resolve()
    if out.exists():
        raise ValueError('Refusing to overwrite an existing formal payload output')
    uefi=args.uefi.resolve();board=args.board.resolve();kernel=args.kernel.resolve()
    symbols=args.symbols.read_text()
    for required in ['_k70_formal_after_vm','_k70_formal_thread_turn','_boot_progress_stage',
                     '_k70_formal_bootstrap','_k70_formal_early_exception','_k70_formal_trap',
                     '_k70_formal_c_entry',
                     '_armcpu_gic_ready','_armcpu_timer_interrupts']:
        if not any(line.split()[-1:]==[required] for line in symbols.splitlines()):
            raise ValueError('Missing diagnostic/platform symbol: '+required)
    report=json.loads(args.kernel_report.read_text())
    seal=json.loads(args.hmac.read_text())
    if report['sha256']!=sha(kernel) or seal['kernel_sha256']!=sha(kernel):
        raise ValueError('Kernel/source-HMAC identity mismatch')
    fd=uefi/'Build/vermeerFormalPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd'
    firmware=verify_firmware(uefi,fd)
    pack=module('formal_pack',uefi/'tools/vermeer-zh/pack_boot.py')
    if len(fd.read_bytes())!=pack.FD_SIZE:
        raise ValueError('FD size differs from verified BootShim packing contract')
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage=Path(tmp);payloads=stage/'EFI/UniXNU/Payloads';payloads.mkdir(parents=True)
        shutil.copy2(kernel,payloads/'kernel.macho')
        adt=payloads/'kernel.macho.adt'
        run(sys.executable,board/'scripts/make-vermeer-adt.py','--output',adt,
            '--dram-size','0x80000000','--owned-memory-size','0x20000000',
            '--cpu-regs','0','--unique-chip-id','1','--chip-id','207')
        tree,seed_offset=blank_identity(adt.read_bytes());adt.write_bytes(tree)
        configuration='''version = 1
[boot]
timeout = 5
default = "xnu"
[kits]
autoload = false
[[entry]]
id = "xnu"
title = "K70 formal source XNU - diagnostic candidate"
type = "xnu"
path = "Payloads/kernel.macho"
args = "-v serial=3 debug=0x14e kt_fixed_zones=120 armcpu-diagnostics=1"
'''
        (stage/'EFI/UniXNU/unixnu.toml').write_text(configuration)
        volume=out/'payload-template.img'
        env=dict(os.environ,MTOOLS_SKIP_CHECK='1',TZ='UTC')
        run('mformat','-C','-F','-T',str(64*2048),'-v','K70FORMAL','-N','4b373046','-i',volume,'::',env=env)
        run('mcopy','-i',volume,'-s','-Q',stage/'EFI','::/',env=env)
        # Read bytes back through FAT, not merely from the staging directory.
        check=stage/'readback';check.mkdir()
        for name in ['kernel.macho','kernel.macho.adt']:
            run('mcopy','-i',volume,'::/EFI/UniXNU/Payloads/'+name,check/name,env=env)
            if (check/name).read_bytes()!=(payloads/name).read_bytes():
                raise ValueError('FAT payload readback mismatch: '+name)
        dtb=uefi/'Resources/DTBs/vermeerFormal.dtb'
        pack.verify_dtb(dtb)
        shim=pack.compile_shim(uefi,stage,'clang','llvm-objcopy','llvm-nm')
        combined=shim+fd.read_bytes();dtb_bytes=dtb.read_bytes()
        packed_kernel=gzip.compress(combined,mtime=0)+dtb_bytes
        kernel_file=stage/'Image.gz-dtb';kernel_file.write_bytes(packed_kernel)
        boot=out/'K70-formal-XNU-TEMPLATE.img'
        run(sys.executable,uefi/'Resources/Scripts/mkbootimg.py','--kernel',kernel_file,
            '--ramdisk',volume,'--base','0','--kernel_offset','0x8000','--ramdisk_offset','0xaa000000',
            '--tags_offset','0x1e00000','--pagesize','4096','--header_version','0','-o',boot)
        sys.path.insert(0,str(HERE.parent/'xnu-preflight'))
        verifier=module('formal_boot_verify',HERE.parent/'xnu-preflight/pack_boot.py')
        boot_proof=verifier.verify_image(boot.read_bytes(),combined,dtb_bytes,volume.read_bytes())
        if boot.read_bytes()[576:608]!=boot_v0_id(boot.read_bytes()):
            raise ValueError('Android header ID differs from the assembled payload')
        # The seed field is a zero placeholder in the public artifact, never a reusable identity.
        metadata={'schema':1,'integration_commit':os.environ.get('GITHUB_SHA'),
            'kernel_sha256':sha(kernel),'adt_sha256':sha(adt),'adt_identity_offset':seed_offset,
            'identity_zero':True,'random_seed_zero':True,'private_boot_candidate':False,'hardware_tested':False,
            'irq_hardware_verified':False,'thread_hardware_verified':False,
            'payload_sha256':sha(volume),'template_sha256':sha(boot),
            'firmware':firmware,'boot':boot_proof,
            'scope':'formal source XNU diagnostics; no root, userland or graphics UI',
            'personalization_required':True}
        (out/'manifest.json').write_text(json.dumps(metadata,indent=2)+'\n')
        (out/'unixnu.toml').write_text(configuration)
        shutil.copy2(adt,out/'kernel.macho.adt')
        shutil.copy2(fd,out/fd.name)
        shutil.copy2(dtb,out/dtb.name)
    (out/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file()))
    return metadata


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['uefi','board','kernel','symbols','kernel-report','hmac','out']:
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(args),indent=2))
