# K70 controlled real exception implementation plan

> REQUIRED superpowers:executing-plans inline, one fresh whole-branch review.

Goal: controlledBRK takenviarealEL1SP0vector, recordsyndrome/state, halt visiblywithoutresume.
Architecture: newdiagnostic/schema overpinnedstage13 bootpath, samestack-freephysicalcleanup and8ROXpages.
Tech Python3.12/Unicorn2.1.4/LLVM/AArch64/GitHubActions/Windowsfastboot.
Spec ../specs/2026-10-29-k70-real-exception-checkpoint.md.

## Global constraints

Samekernel/3offsets[3f7290,3f733c,9e1e80]/16vectors/8pages/caller76+RET4/208Bframe124writes. BRK4B14→ESRF2004B14/ELRtriggerPC; preSPSel0/SP...BFBF30→postSPSel1/SP...C04000/vector0. SPSRmaskF00003DF. FARrawnotvalidforBRK. One-shotarm1024/busy1032/maskedSPSR1040/preLR1048.36fieldsnewexplicitlayout,704/38/1384/1440. NoERET/deeperC/partitionwrites; eachbootfreshseed.

## Review focus

- RealSPbank/vectorselection andSPSR/ELR semantics must not be copiedfromoldsyntheticvector4tests.
- Dirtyrecordexistsbeforetrap; failedrecordATcannotdisableMCI or touchunverifieddata.
- Busy/armedstate mustpreventnested/unrelated/fallthroughpathsfromfalsePASS.
- FARrandom/unknown mustnotbecertifiedasfaultaddressforBRK; capturesmustprecedecleanupclobbers.
- Sharedcachecleanup mustcoveroriginalCframeandallrecordwrites oneveryMCIoffpath, with nohandlerstackaccess/ERET.

### Task1: Dedicated diagnostic and model

Files xnu-exception-checkpoint/{test_blobs.py,blobs.py,checkpoint.S,renderer.S,transition.S}.
Interface build(kernel,out)->header,proof; execute()->37u64record,state,colors.
- [x] REDmissingbuilder; modelBRK+SPSR+SPbank, positive andallcriticalnegativeclasses in spec.
- [x] Implementprecontract/arm/BRK/stack-freecapture/one-shotexpectedgate/failclosedrecord+framecleanup/renderer, GREEN andinspectrender.

### Task2: Package and CI

Files prepare.py,test_prepare.py,README.md,requirements.txt,.gitignore,newworkflow.
- [x] REDnewpackage/preimportpins/36fieldlegend+8pages; minimalpinnedstage13wrapper, GREEN.
- [x] CI198prior+newcoverage, YAML/bash/Pythonvalidation, savenativeELF/proof.

### Task3: Review, actual artifact, one device attempt, archive

- [x] Onefreshfinalreview, noImportantfixneeded, publishcompare15objects.
- [x] Cloud19steps/20new+198prior; independent26fileFD/FV/PE/nativeELF/BRKopcode/vector/profile/zeroseedproof.
- [x] ActualFASTBOOTreadiness, freshseedoneboot, photoESRF2004B14/ELRFFFFFFF0086086C4/SP0toSP1/phase2verified1.
- [x] Centralreport/index/qualitygates/sourcecloseout;6355filefullSHAauditzero mismatches beforedoccloseout; finalrefresh/audit aftercloseoutmetadata.

## Ledger

- Ruling: reusecleanfeatureclone/newbranchk70-exception-probe; preserveoldwork. Existinguserauthorizationcoversreview/publication/oneboot, no repeatmenus.
- Ruling: newdedicatedschemaanddiagnostic, retainunchangedstage13 and198priorregressions. Cost: oldalias/scratchdisplayfieldsnotrepeated, explicitnewlegendrequired.
- Ruling: unknownrecordmappingnowfailsclosedM1 instead ofoldemergencyM0 becausepretraprecorddirty. Cost: suchfailuresmayonlyleaveearlydisplay/manualFASTBOOT, notrecoverysuccess.
- Ruling: uniqueBRKcapturesandhaltswithoutERET. FARisrawonly. Cost: provesonecontrolledsynchronouscase, notarbitraryfaultrecoveryortimerIRQ.
