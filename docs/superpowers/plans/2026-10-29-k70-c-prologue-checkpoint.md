# K70 C prologue implementation plan

> REQUIRED SUB-SKILL superpowers:executing-plans inline; one fresh final review.

Goal: observe exact original C prologue60B and bounded124byte frame writes, beforefirstBL.
Architecture: stage10 wrapper/newdiag, same7ROX/ownership pipeline, shared physical Cframecleanup andfailclosed M1halt.
Tech: AArch64LLVM,Python/Unicorn2.1.4,GithubActions,Windowsfastboot.
Spec: ../specs/2026-10-29-k70-c-prologue-checkpoint.md

## Global constraints

No oldstage changes. SamekernelSHA5fcfc61a...,BA/guard/map/seed profile. Only3wordoffsets[3f7290,3f733c,9e1e70]+16vectors. Preserve exact60Bprefix and nevercall firstBL97e83189. Diagnostic<=4096. Frame208B atKVAFFFFFFF007BFBF30,124originalwrites. AllMCIoff paths cleanverifiedframe orhaltM1.34fields/eightbands/lastrow1344/footer1440.

## Review focus

- Partial original STP and emergency recordAT rejection must not discard dirtyframecache beforeM0.
- Failed frame translation/redirect/cacheline geometry must haltM1 without touchingfailedaddress orpaintingfalsePASS.
- Snapshot expected x19 (original LR) and old x29 before originalmov/frame writes; originalstore whitelist must catch alias escapes.
- Newframechecks/renderer must not overwrite stage10 meanings, diagnostic data buffers orUEFIfooter.
- Generator/publishedFD must bind changedBLoffset/originalprefix/globalguard/7pages;no oldstage filemutation.

### Task1: Original prefix and cache-safe diagnostic

Files xnu-c-prologue-checkpoint/{test_blobs.py,blobs.py,checkpoint.S,renderer.S,transition.S}.
Interfaces build(kernel,out)->header,proof; same layout andoldextractors. Execute fixture->record35u64,state,8colors with optionalM1failhalt.
- [x] Adapt stage10tests for newpatch/60Ballowedwrites/34fields/failclosedframecleanup, add exactpartialwrites/negativeABI/frame tests. REDmissingbuilder.
- [x] Implement BLinterception, snapshots/framevalidation/sharedcleanup/M1halt, GREEN full instruction suite; inspecteightbandhostrenderer.

### Task2: Generator and cloud path

Files {prepare.py,test_prepare.py,README.md,requirements.txt,.gitignore},.github/workflows/k70-c-prologue-checkpoint.yml.
- [x] REDpackage7pages/hash-beforepatch/display/oldstagepreservation; minimalhashpinnedstage10wrapper, GREEN.
- [x] Newworkflow restoresdurablekernel,runs allprior131+restore16+newtests; YAML/bashvalidation; nativeblobs savedforCIcomparison.

### Task3: Review, publication, one boot and archive

- [ ] Onefreshfinalreview;fixImportantRED→GREENonce/fullsuite, publishsource/workflowafterclear,compareallremoteobjects.
- [ ] CIactualcounts/logs,download/hash/FD-FV-PE/ELF/prefix/globalguard/3patches/7pages/template checks.
- [ ] NewprivateOSseedonlyafterverification; FASTBOOTreadinessactualcheck; exactlyoneboot/photoactualoutcome.
- [ ] Centralstage12report/index/catalogfullaudit;state exactbefore-first-call boundary.

## Ledger

- Pre-flight: Task1header/proof interfaces consumed byTask2generator;34fields geometry matchedexactly withfooter1440. Task3comparesnativeblob againstCIactualembeddedPE beforeboot.
- Ruling: keep originalCframe writes in ownedRAM rather than rollback; this is intentional prologue state, no returnafterEBS. Cost: records prove boundedwrites/cacheclean rather than originalRAMrestoration.
- Ruling: cleanupAT/CTR failure haltsM1withoutnewbands; clearingMCI through unknownframewoulddiscarddirtycache. Cost: phonephoto may remain on pretransitionUEFI text and requiresmanualPower+VolDown.
- Ruling: previoususerdelegationcoversdesign/publish/oneboot; no repeatapproval questions. Use existingcleanfeatureclone. Logs/ledgercentral peruserpreference.
- Ruling: pinned common_start MOV x19,x30 atVAFFFFFFF0073FB2A4 changes incoming x19 before C; snapshot originalLR plusoldFP, not incomingx19. Evidence: first positive model rejected savedx19; raw original disassembly identifies the producer. Cost if wrong: valid frame would reject, not silently pass.
- Ruling: asynchronous exception injection covers nine store-instruction boundaries (write callback counts2,4,6,8,10,12,13,15,16); Unicorn STP emits two callbacks within one instruction. No claim of intra-instruction asynchronous interrupts or arbitrary synchronous partial-store recovery. Cost: those unavailable/higherEL failure modes can prevent diagnostics.
- Ruling: row1344 is the final glyph start,1378 its final pixel; report record_last_row=1378 and keep footer1440. Cost if wrong: overlap would obscure context; host render inspected.
- Ruling: runtime cache-geometry fixtures use16,64,128,4096-byte lines, matching the unchanged transition's16..4096 admission. A4-byte fixture halted in that earlier transition as designed, before C; no production relaxation. Cost: geometry outside the admitted range is rejected rather than tested as a C pass.
- Verification: original131+restore16 PASS in central suite logs; final new24/24 PASS175.181s.19missingbuilderRED→GREEN and3missingpackageRED→GREEN; changed-stage10-builder regression RED(unreviewed module executed)→GREEN1.789s after moving all10source hashes before prior import/output. YAML1/bash7PASS; host render inspected; native checkpoint3684B SHAda5906cb006290e1a0c4263ff0a79a5d664238a17fb8b136fd75f4dd45be0d84, transition552B SHAc847661d876e5c9ce40c54f6fbe81870dfb579b753510ec8af3dac01f47ec842. Total171 test instances; no hardware claim yet.
