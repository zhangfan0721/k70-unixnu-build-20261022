"""Fail closed on inherited write paths, private inputs, or scope expansion."""
from pathlib import Path
import hashlib
import json
import re
HERE=Path(__file__).resolve().parent
def check():
    files={p.name:p for p in HERE.iterdir() if p.suffix in ('.h','.inc') and not p.name.startswith('test_')}
    text='\n'.join(p.read_text() for p in files.values())
    code=re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
    for word in ('hostWrite4k','hostSyncCache','smmuBypassStream','native_ufs_store_',
                 'native_ufs_log_','native_ufs_export_','verified_root','hostStoreOpen','hostLogOpen'):
        if word in code:raise ValueError('Forbidden compiled implementation: '+word)
    commands=(HERE/'ReadOnlyCommands.inc').read_text()
    if commands.count('K70UfsPolicy::command(lun,cdb,cdbLength,direction,dataBytes)')!=1:
        raise ValueError('Missing SCSI policy gate')
    if commands.count('if (direction == 1) return kIOReturnNotPermitted;')!=1:
        raise ValueError('Missing data-out rejection at submit boundary')
    if 'hostScsi (0xd0' in code:raise ValueError('Unexpected power-state command')
    offsets=set(int(x,16) for x in re.findall(r'hostWrite\s*\(\s*(0x[0-9a-f]+)',code))
    if offsets!={0x20,0x24,0x50,0x54,0x58,0x60}:raise ValueError('Controller write-set changed')
    # Two physical store targets: HC plus the bounded SMMU callback. GCC and
    # storage-media write implementations remain excluded.
    stores=re.findall(r'write32\s*\(([^;]+)\);',code)
    if stores!=['gHost.hc, offset, value','gHost.smmu,o,v']:raise ValueError('Physical store target changed: '+str(stores))
    if 'k70ConfigureUfsSmmu(plan,smmuRead' not in code or 'k70DmaDescriptors(' not in commands:
        raise ValueError('Missing bounded SMMU/DMA submission path')
    return {'scope':'LUN0 fixed GPT blocks only','storage_writes':False,
            'smmu_configuration_writes':True,'smmu_write_scope':'one new SID0x60 route; five register targets; no CR0 or other routes',
            'hardware_dma_isolation':False,'persistent_log':False,
            'root_authentication_changed':False,'hardware_tested':False,
            'files':{n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in sorted(files.items())}}
if __name__=='__main__':print(json.dumps(check(),indent=2))
