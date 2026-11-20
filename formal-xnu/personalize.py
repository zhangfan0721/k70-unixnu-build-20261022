"""Create a fresh LOCAL private candidate. Never boots, flashes, or contacts a device."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import struct
import subprocess
import tempfile
from payload import handoff, blank_identity, boot_v0_id


def fill_identity(blob, fresh, fresh_random):
    blank,offset=blank_identity(blob)
    if blank!=blob or len(fresh)!=8 or fresh==bytes(8) or len(fresh_random)!=64 or fresh_random==bytes(64):
        raise ValueError('Expected a zero template and one fresh nonzero identity')
    result=bytearray(blob);result[offset:offset+8]=fresh
    marker=b'random-seed'.ljust(32,b'\0')+struct.pack('<I',64)
    at=blob.index(marker)+len(marker)
    result[at:at+64]=fresh_random
    parsed=handoff.parse_tree(result)['/chosen']
    if parsed['unique-chip-id']!=fresh or parsed['random-seed']!=fresh_random:
        raise ValueError('Private identity update failed')
    return bytes(result)


def build(template,manifest,out):
    info=json.loads(manifest.read_text())
    original=template.read_bytes()
    if not info.get('identity_zero') or not info.get('personalization_required') or \
            hashlib.sha256(original).hexdigest()!=info['template_sha256']:
        raise ValueError('Not the verified public zero-identity template')
    if out.exists() or out.parent.name!='private' or out.suffix!='.img':
        raise ValueError('Use a NEW .img path inside a directory named private')
    if original[:8]!=b'ANDROID!' or len(original)<4096:
        raise ValueError('Invalid boot template')
    if original[576:608]!=boot_v0_id(original):
        raise ValueError('Public template Android ID mismatch')
    ks,_,rs,ra,_,_,_,page,version,_=struct.unpack_from('<10I',original,8)
    if (ra,page,version)!=(0xaa000000,4096,0) or not ks or not rs:
        raise ValueError('Unexpected boot template layout')
    start=page*(1+(ks+page-1)//page)
    if start+rs>len(original):
        raise ValueError('Truncated ramdisk')
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);volume=root/'payload.img';adt=root/'kernel.macho.adt'
        volume.write_bytes(original[start:start+rs])
        env=dict(os.environ,MTOOLS_SKIP_CHECK='1')
        remote='::/EFI/UniXNU/Payloads/kernel.macho.adt'
        subprocess.run(['mcopy','-i',str(volume),remote,str(adt)],check=True,env=env)
        if hashlib.sha256(adt.read_bytes()).hexdigest()!=info['adt_sha256']:
            raise ValueError('FAT ADT does not match the verified public template')
        fresh=secrets.token_bytes(8)
        while fresh==bytes(8): fresh=secrets.token_bytes(8)
        fresh_random=secrets.token_bytes(64)
        while fresh_random==bytes(64): fresh_random=secrets.token_bytes(64)
        private_adt=fill_identity(adt.read_bytes(),fresh,fresh_random)
        adt.write_bytes(private_adt)
        subprocess.run(['mcopy','-o','-i',str(volume),str(adt),remote],check=True,env=env)
        check=root/'check.adt'
        subprocess.run(['mcopy','-i',str(volume),remote,str(check)],check=True,env=env)
        if check.read_bytes()!=private_adt or volume.stat().st_size!=rs:
            raise ValueError('Private FAT readback failed')
        result=bytearray(original);result[start:start+rs]=volume.read_bytes()
        result[576:608]=boot_v0_id(result)
    out.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation prevents reusing or replacing an existing private image.
    with out.open('xb') as stream: stream.write(result)
    record={'template_sha256':info['template_sha256'],
        'private_sha256':hashlib.sha256(result).hexdigest(),
        'fresh_identity_generated':True,'fresh_random_seed_generated':True,
        'device_operations':False,'boot_attempts':0,
        'scope':'LOCAL PRIVATE: never upload; separate device authorization required'}
    out.with_suffix('.local.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['template','manifest','out']: parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.template,args.manifest,args.out),indent=2))
