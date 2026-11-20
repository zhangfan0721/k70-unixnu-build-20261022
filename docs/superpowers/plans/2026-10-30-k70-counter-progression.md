# K70 Counter Progression Implementation Plan

> REQUIRED superpowers:executing-plans inline; ONE fresh whole-branch review, no implementer agents or per-task reviews.

Goal: THREE ordered samples of each physical/virtual counter across TWO bounded intervals, stable reported frequency and no timer programming.
Architecture: dedicated stage15 diagnostic over pinned stage14 precontract/cleanup; same original caller/RET/patch/page ownership. New explicit36field schema, models separate from hardware.
Tech: AArch64/LLVM/Python3.12/Unicorn2.1.4/GitHubActions/Windowsfastboot.
Spec: ../specs/2026-10-30-k70-counter-progression.md.

## Global constraints

KernelSHA5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8; offsets3f7290/3f733c/9e1e80/16vectors/8ROXpages/<=4096Bdiag; frame208B/124writes; loops4096+8192;3samples/channel;freq0<value<=1e9stable; strictunsignedincrease,totaldelta<freq; ISB before each counterread. No timer/GICwrites,IRQ/unmask/ERET/relocation/flash. One fresh seed per attempt.

## Review focus

- Frequency is firmware metadata; no claim of measured absolute frequency or exact cross-counter offset.
- Ordinary success and unexpected exceptions must never share a PASS path; dirty-record AT failure stays MCIon.
- Pre-layout legacy snapshot words cannot appear as valid frequency/sample/frame fields on early rejection.
- Real unsigned counter values near2^64, wraps, unequal virtual offsets/deltas, and host counter modeling must match the stated bounded contract.
- No unbounded polling or timer/GIC programming; ordered six reads and frame/record cleanup must hold across every exit.

### Task1: Diagnostic + modeled instruction tests
Files xnu-counter-checkpoint/{test_blobs.py,blobs.py,checkpoint.S,renderer.S,transition.S,requirements.txt,.gitignore}.
Interfaces build(kernel,out)->header,proof; execute(counter_sequences/faults)->record,state,colors.
- [x] RED missing counter builder; tests for3samples+2intervals, stablefrequency, negativeclasses in spec, no timer writes/barriers and explicit ready/token semantics.
- [x] Minimal diagnostic and builder with pinned stage14 sources before import; GREEN focused then full newbehavior suite once.
- [x] Inspect native disassembly/size, write trace and render; commit.

### Task2: Package + CI
Files prepare.py,test_prepare.py,README.md,.github/workflows/k70-counter-checkpoint.yml.
Interfaces generated Entry.c/EntryBlobs.h,entry-package.json new36schema; artifact K70-XNU-counter-template.img+ELF/proof.
- [x] RED newpackage/pins/legend/8pages; minimal pinned14wrapper GREEN.
- [x] Workflow runs218 prior instances+new suite, proves actual embedded counter blobs and private-zero-seed policy; parseYAML/bash/Python; save nativeproof, commit.

### Task3: Review/publish/artifact/device/archive
- [x] One fresh final reviewer clean, noImportantfix/re-review;15publishedobjects comparedremote.
- [x] Cloud20new+218prior/19steps, actual26filemanifest/FD-FV-PE/nativeELF/MRSISB/loop/zero seed proof.
- [x] FASTBOOT readiness, newOSseed, ONEboot and originalphoto:both3samples strictincrease,49/97intervals,146total,reported19200000Hzstable;kind0/frame1/verified1.
- [x] Central report/index/current/navigation and docs closeout;6857file/500stage15 fullSHAauditzero beforecloseoutmetadata,refresh/auditafterlastwrites. Preserve raw evidence and archivedledger/diff; retainignoredscratchunderpriorcleanup-policyprecedent,no deletionretry.

## Rulings
- Existing user delegation covers routine design/publication/one temporary boot; keep isolated clean clone/newbranch and historical dirty directory unchanged.
- Bundle both counter channels,3samples/stablefreq in one boot; defer IRQ. Cost: this proves no interrupt delivery or full scheduler clock.
- Dedicated schema avoids growth beyond owned page. Cost: do not reuse stage14 field meanings; exception rawSPSR moves to18.
- Reject wraps/totaldelta>=freq for this short experiment. Cost: a real counter wrap or long firmware pause can reject; no external timing calibration is claimed.
