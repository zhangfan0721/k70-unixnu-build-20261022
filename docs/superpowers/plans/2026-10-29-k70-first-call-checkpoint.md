# K70 first call checkpoint implementation plan

> REQUIRED superpowers:executing-plans inline; one fresh whole-branch final review.

Goal: original first BL/RET plus header-read; stop before relocation conditional branch.
Architecture: newstage13 layer over hash-pinned12, same stack/physicalcleanup,8ROXpages,36fields.
Tech: Python3.12/Unicorn2.1.4/AArch64LLVM/GitHubActions/Windowsfastboot.
Spec: ../specs/2026-10-29-k70-first-call-checkpoint.md

## Global constraints

Pinned kernel5fcfc61a...; patch[3f7290,3f733c,9e1e80]+16vectors. Preserve caller76B andRET4B; originalTBNZ notexecuted. Header00200001/baseFFFFFFF007004000/liveLRFFFFFFF0079E5E74. Frame208/124 unchanged; snapshotoldLRexpected...5E34. New8thROX8803F2000. Diagnostic<=4096,fields00..23/start704/pitch38/last1384/footer1440. No partition operations; every boot newseed.

## Review focus

- LiveLR changed byBL must not be confused with saved pre-callLR in originalframe.
- Incomingflags/base snapshots must survive record-AT emergency and avoid visible/private record collisions.
- Original conditionalbranch must remain intercepted even for corrupt high-bit flags; no relocation/global store can run.
- Eighthcallee page must participate in all ROX/rollback/cache publication loops and actualFD proof.
- Header/callee source hashes and CI claims must describe emptyRET and actualbodyentry accurately, without implying TBIenablement/fullOS.

### Task1: Real call model and diagnostic

Files xnu-first-call-checkpoint/{test_blobs.py,blobs.py,checkpoint.S,renderer.S,transition.S}.
Interface build(kernel,out)->header,proof; execute->37u64record,state,8colors.
- [x] REDmissingbuilder; adapt prior instruction tests, exactordered16storetuples, BL/RET trace, invalidLR/base/flags, exceptions atcallee/headerreads and beforeoriginalTBNZ.
- [x] Implement interception/snapshots/frameoldLR/newchecks/36fieldrenderer, GREEN meaningfulsuite and inspectrender.

### Task2: Package and workflow

Files {prepare.py,test_prepare.py,README.md,requirements.txt,.gitignore},newworkflow.
- [x] RED8pagepolicy andpreimportpin/oldstagepreservation; implement minimalstage12wrapper, hashcaller76/callee4 beforepatch and8permissionloops, GREEN.
- [x] Workflow allprior171+newtests, YAML/bash/Pythonchecks, nativeblobs/proof ready.

### Task3: Review, CI, device, archive

- [ ] Onefreshfinalreview, fixImportantonceRED→GREEN/fullrelevanttests, publishandcompareallsourceobjects.
- [ ] CIactualcounts/logs,downloadandindependentFD/FV/PE/ELF/header/callee/8pages/zerotemplateproof.
- [ ] FreshseedandonebootifactualFASTBOOTconnected; photoevidencebeforehardwarePASS.
- [ ] Centralreport/index/catalogfullhashaudit andstate exactpre-relocationboundary.

## Ledger

- Ruling: reuse isolatedcleanfeatureclone; newbranchk70-first-call. Existinguserdelegationcoversdesign/publish/temporaryboot; norepeatedmenus. Olddirtycheckoutpreserved.
- Ruling: emptyfirstcallee is not TBI configuration; execute headerread too, stop beforeoriginalTBNZ even forbadflags. Cost: relocationandTBIbehavior remainunproven.
- Ruling: retain8bands andappend2fieldsatpitch38. Cost: glyphspacing3pixels, validatehostrenderbeforepublication.
- Ruling after external read-only reports: complete this already bounded BL/RET/header-read slice, then prioritize real synchronous exception capture and timer counter/IRQ evidence before deeper C initialization. No claim that stage/test counts or unweighted3/5 express OS progress. Cost: deeper boot work waits for observability evidence; no arbitrary time/probability stop rule adopted.
- Task1/2 initial verification:27tests missingbuilder/package RED0.043s, then27/27GREEN204.903s including exactordered16writecallbacks, realcalleeRET trace, high-bitheader rejection beforeconditional, fourcallee/header exception sites, oldframe/cleanup tests and8pagehostpolicy. Prior171 regressions remain scheduled once in cloud; no redundant local rerun of unchanged old stages.
