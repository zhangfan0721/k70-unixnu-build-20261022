"""Fail closed on inherited write paths, private inputs, or scope expansion."""
from pathlib import Path
import hashlib
import json
import re
HERE=Path(__file__).resolve().parent
def check():
    files={p.name:p for p in HERE.iterdir() if p.suffix in ('.h','.inc') and not p.name.startswith('test_')}
    # Inspect the actual transitive include set, not preserved, uninstantiated
    # planners/writers that this diagnostic candidate never includes.
    compiled={}
    def include(name):
        if name in compiled:return
        text=files[name].read_text();compiled[name]=text
        for dependency in re.findall(r'^\s*#\s*include\s+"([^"]+)"',text,re.M):
            if dependency in files:include(dependency)
    include('K70UfsTransport.inc')
    text='\n'.join(compiled.values())
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
    transport=compiled['K70UfsTransport.inc']
    if 'ReadOnlyCommands.inc' in compiled or 'RootQueue.h' in compiled or 'Qualification.inc' in compiled:
        raise ValueError('Qualification compiles UFS command/queue/DMA code')
    for word in ('hostWrite','hostStopQueue','hostStartQueue','hostScsi','hostNop','write32','read32',
                 'IOBufferMemoryDescriptor','IOLockAlloc','k70qualify'):
        if word in transport:raise ValueError('Unexpected transport operation: '+word)
    if transport.count('*reinterpret_cast<volatile uint32_t *>(smmu+o)=v;')!=1:
        raise ValueError('SCTLR store boundary changed')
    if transport.count('mapPhys(')!=2 or 'mapPhys(0x1d84000,0x3000,hcMap)' not in transport:
        raise ValueError('Map scope changed')
    if 'k70ReadWriteTranslation(smmu+0xc5000)' not in transport:
        raise ValueError('Missing write permission qualification')
    qualify=compiled['K70SctlrQualification.h']
    for required in ('offset!=0xc5000','value!=0','wrote || rejected',
                     'k70SmmuSnapshotSame(p,read)','},true)'):
        if required not in qualify:raise ValueError('Missing single-write gate: '+required)
    upstream=compiled['SmmuTakeover.h']
    if 'if (disableOnly) return nullptr;' not in upstream:
        raise ValueError('Missing upstream disable-only stop')
    if 'bool pass=hostBringUp' in transport or 'k70CollectSmmuEvidence' in transport:
        raise ValueError('Stale diagnostic entry')
    return {'scope':'single bank69 SCTLR zero/writeback qualification; no UFS transport','storage_writes':False,
            'smmu_configuration_writes':True,'controller_takeover':False,
            'smmu_write_scope':'one 32-bit store PA0x150c5000 value0; no other SMMU or HC writes',
            'hardware_dma_isolation':False,'persistent_log':False,
            'root_authentication_changed':False,'hardware_tested':False,
            'compiled_files':sorted(compiled),
            'files':{n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in sorted(files.items())}}
if __name__=='__main__':print(json.dumps(check(),indent=2))
