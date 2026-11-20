# K70 original XNU MMU checkpoint (stage09)

Research diagnostic for Redmi K70/vermeer, unlocked bootloader. It is not a usable iOS image. Use only the reviewed zero-seed template plus a fresh private seed with `fastboot boot`; never flash/erase partitions. Android storage is not mounted. No original arm_init, scheduler, drivers or userland runs.

The pinned source-built kernel is SHA256 `5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8`. Stage08 source is hash-pinned and remains unchanged. The original firstCPU prefix and16-byte TTBR helper remain intact. Instrumentation changes exactly3 common_start words: entry ADRP becomes a gate branch, VBAR write becomes NOP to keep physical low vectors, and the instruction after original SCTLR/ISB becomes a branch to a separate owned diagnostic page. Each of16 low vector slots changes only its first branch. Unrelated kernel text is preserved.

Before the existing256MiB boot window, UEFI must allocate a separate16KiB prefix guard at880000000 as EfiLoaderData. Both allocations, system-RAM/identity checks, ordinary WB permissions and actual memory-map ownership receipts are required. No forcing allocation or fallback addresses. Initial XNU mappings cover880000000..890000000; the allocation ends890004000. Its final16KiB is initially unmapped and is tested only with AT, never by data access. Guard and window are freed only on a normal pre-EBS return; nothing is freed after an EBS attempt. Existing bounded retry, permission rollback and instruction publication are retained.

Exactly6 UEFI ROX pages:8803f9000,8803fb000,881604000,8803fa000,8803ff000,881608000. XNU's original block descriptors are RWX, as built by the original prefix; the diagnostic does not claim to implement final kernel W^X. Runtime conservatively requires40-bit PA capability and4KiB support. The original TCR/TTBR0/TTBR1/MAIR/SCTLR sequence executes. Before the first M1 data write the record translation is checked. The checkpoint then verifies physical and kernel aliases, reads boot_args through KVA, checks the guard/map boundary/tail fault, writes/reads/restores16 stack bytes, cleans touched record and stack cache lines, disables M/C/I, and renders. The whole allocation is never cache-walked under XNU M1, and GOP is never accessed then.

The exception path handles EL1 vector entries only. Mapping failures preventing instruction fetch, traps at higher ELs, asynchronous hardware effects and a guaranteed recovery are not established by host tests. Shared host backing makes physical/KVA data aliases coherent in tests; AT/PAR, privileged registers, cache, DAIF and SPSel are explicit models. CI passing is not hardware proof.

Stack-test state is0 when untouched,2 before a potentially dirty test write and1 after successful restore. Only a touched stack line is cleaned. An EL1 exception during the stack test retains2 and cleans the diagnostic scratch stack before halting; it does not claim the interrupted test restored its16 bytes. No original kernel execution resumes.

Six bands purple/orange/blue/white/green/cyan plus record00=0 show this checkpoint passed. Red indicates rejection/EL1 exception.31 little-endian u64 words: magic; kind,cause,EL,SCTLR,VBAR,ESR,ELR,FAR,SP,LR,x20..26,TCR,TTBR0,TTBR1,MAIR,PARphysical,PARkernel,PARargs,PARstack,PARguard,PARlast,PARtail,alias-word,stack-test. Visible IDs00..1D omit magic. Kind0 pass/1 exception/2 rejection; rejection causes1 registers,2 table,3 configuration/translation,4 record translation,5 stack. All checks end in a halt before arm_init. Recover using Power+VolDown for FASTBOOT.

Run host checks with Python3.12, Unicorn2.1.4, Clang/LLD/LLVM and a C compiler:

```
python -m unittest discover -s xnu-mmu-checkpoint -v
```

Set K70_KERNEL/K70_UEFI_SOURCE/K70_DTB to the pinned inputs when outside the local research workspace. Keep private seeded images, phone photographs and raw phone data out of the repository. Cloud workflow packs a public zero-seed template; regenerate private entropy for every real boot.
