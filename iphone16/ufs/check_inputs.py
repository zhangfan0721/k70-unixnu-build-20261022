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
    if commands.count('gWake.permit(lun,cdb,cdbLength,direction,dataBytes)')!=1:
        raise ValueError('Missing stateless and one-shot SCSI command policy')
    if commands.count('if (direction == 1) return kIOReturnNotPermitted;')!=1:
        raise ValueError('Missing data-out rejection at submit boundary')
    if commands.count('hostTransportOwned()')!=3:
        raise ValueError('Missing ownership gate before buffer/descriptor/doorbell use')
    if 'if(opcode!=3 || idn!=2)return kIOReturnNotPermitted;' not in commands:
        raise ValueError('Query range changed')
    required={'K70HostIO.h','K70Takeover.inc','K70Smmu.h','SmmuTakeover.h',
              'RootQueue.h','ReadOnlyCommands.inc','Qualification.inc'}
    if not required<=compiled.keys() or 'K70SctlrQualification.h' in compiled:
        raise ValueError('Integrated include set changed')
    transport=compiled['K70UfsTransport.inc'];takeover=compiled['K70Takeover.inc']
    io=compiled['K70HostIO.h']
    if transport.count('k70_ufs_readonly_qualify(void)')!=1 or 'if(entered)return;entered=true;' not in transport:
        raise ValueError('Missing exclusive one-shot entry')
    stores=re.findall(r'\*reinterpret_cast<volatile uint32_t \*>\s*\([^;]+?\)\s*=',code)
    if len(stores)!=1 or io.count('*reinterpret_cast<volatile uint32_t *>(base+offset)=value;')!=1:
        raise ValueError('Raw MMIO store escaped the checked boundary')
    if '*reinterpret_cast<volatile uint32_t *>' in transport or '*reinterpret_cast<volatile uint32_t *>' in takeover:
        raise ValueError('Direct MMIO outside checked IO')
    if 'k70ReadWriteTranslation(va)' not in io or 'translationOK(base+offset,pa,true)' not in io:
        raise ValueError('Missing per-write permission/PA/attribute validation')
    for required in ('configuredIdentity()', 'hcIdentity(', 'listIdentity()', 'K70HostPhase::Ending',
                     'K70HostPhase::Transport', 'K70HostPhase::Configuring'):
        if required not in io:raise ValueError('Missing phased write gate: '+required)
    offsets=set(int(x,16) for x in re.findall(r'hostWrite\s*\(\s*(0x[0-9a-f]+)',code))
    if offsets!={0x20,0x24,0x50,0x54,0x58,0x60}:raise ValueError('Controller write-set changed')
    if takeover.count('hostScsi(0xd0,cdb,6,false,0,500000,&scsi)')!=1:
        raise ValueError('ACTIVE wake call scope changed')
    for word in ('attempt <','attempt<','IOSleep','while (','while('):
        if word in takeover:raise ValueError('Unexpected retry/wait loop in integrated entry')
    if 'gWake.observe(power)' not in takeover or 'if(gWake.needed())' not in takeover:
        raise ValueError('Wake is not bound to a successful power query')
    if 'hostWrite(0x60,0)' not in takeover or 'gCleanupAttempted=true' not in takeover:
        raise ValueError('Missing bounded terminal stop')
    return {'scope':'one integrated UFS takeover, optional single ACTIVE wake, capacity/GPT/four hashes',
            'storage_writes':False,'smmu_configuration_writes':True,'controller_takeover':True,
            'smmu_write_scope':'bank69 SCTLR0/CBA2R1/CBAR0x10000; one new SID0x60 route; readback at every step',
            'hc_write_offsets':[hex(o) for o in sorted(offsets)],'wake_once_if_power_requires':True,
            'command_retries':False,'root_published':False,
            'hardware_dma_isolation':False,'persistent_log':False,
            'root_authentication_changed':False,'hardware_tested':False,
            'compiled_files':sorted(compiled),
            'files':{n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in sorted(files.items())}}
if __name__=='__main__':print(json.dumps(check(),indent=2))
