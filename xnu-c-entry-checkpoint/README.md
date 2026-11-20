# K70 virtual arm_init entry checkpoint (stage10)

Research diagnostic, not a complete XNU/iOS system. Stage09 already demonstrated original MMU enable on the connected K70. This stage permits the original cold common_start tail to execute CPACR/TPIDR setup and RET to virtual arm_init. It intercepts that address before its first original C instruction; no C prologue, relocation, platform callbacks, storage drivers or userland runs.

Same pinned source kernel5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8; fixed guard880000000+16KiB and BA880004000+256MiB; original map ends890000000, final16KiB of allocation remains initially unmapped and AT-only. Stage09's allocation, GCD/WB/identity, memory-map LoaderData receipts, bounded EBS attempts, rollback and instruction publication remain required. No forcing an occupied allocation and no fallback addresses.

Only3 instruction words change: common gate at offset3f7290, physicalVBAR-preserving NOP3f733c, and arm_init firstword9e1e34. All16 low-vector first branches are redirected to diagnostics. The old post-MMU interception at3f7358 is removed; its original52-byte cold tail through RET is preserved. Original firstCPU564-byte prefix and16-byte TTBR helper remain untouched. The original60-byte C-entry prefix is independently hashed before its firstword replacement.

Exactly7 UEFI ROX pages:8803f9000,8803fb000,881604000,8803fa000,8803ff000,881608000,8809e5000. XNU's initial original block descriptors remain RWX; final kernel W^X is not implemented here. Diagnostic PA881608000 is entered at KVAFFFFFFF008608000 via original arm_init VAFFFFFFF0079E5E34. Inbound x0 must be boot_args KVAFFFFFFF008548000, CPACR=300000, TPIDR_EL1=0, and the previous MMU/register/alias/stack contract must still pass.

Before every MMU-disable path, including emergency record-translation failure, an alias-invariant ADR offset plus the fixed owned PA base branches to physical instructions. Clearing M/C/I while fetching a KVA is forbidden. The same bridge works when physical EL1 vectors enter the physical alias. Record and touched diagnostic stack lines are cleaned before MCIoff; no GOP under XNU M1 and no whole-BA cache walk across the unmapped tail. Stack state0=untouched,2=potentially dirty/interrupted,1=read/write/restored; an interrupted diagnostic never resumes original code.

Seven success bands add magenta at rows512..575.32 hex fields00..1F startrow640, two columns of16, lastrow1334; retained UEFI context starts1440. Kind0 plus all seven bands means this bounded checkpoint passed. IDs00..1D keep stage09 meanings;1E=diagnostic entry ADR (expectedFFFFFFF008608000),1F=inbound x0 (expectedFFFFFFF008548000). Red means rejection or EL1 exception. Photo values are required for a hardware conclusion; fastbootOKAY only means the phone accepted the image.

Tests execute real original instructions/RET/branches with shared physical/KVA memory. System registers, AT/PAR, cache, DAIF and SPSel are explicit models. Higher-EL traps, unavailable instruction fetch or arbitrary corrupted mappings can prevent diagnostics. Host tests do not guarantee hardware recovery.

Use the cloud workflow, then independently verify ZIP hashes, actual FD/FV/PE and local ELF/patch hashes. Generate a fresh private PC CSPRNG seed from the public zero-seed template for EACH boot. Use `fastboot boot` only; never flash/erase partitions. Private seeded images, photos and raw phone data stay local. Recover from the halt using Power+VolDown for FASTBOOT.

```
python -m unittest discover -s xnu-c-entry-checkpoint -v
```

Requires Python3.12, Unicorn2.1.4, Clang/LLD/LLVM and a C compiler. Set K70_KERNEL/K70_UEFI_SOURCE/K70_DTB to pinned inputs when outside the research workspace.
