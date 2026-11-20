# Stage15: bounded physical and virtual counter progression

Hardware PASS2026-10-30. This dedicated read-only probe retains the pinned
stage14 precontract, original76-byte caller/emptyRET4,16vectors and8UEFI ROX
pages. It stops before relocation. Stage14's real BRK hardware evidence stays
unchanged; this probe deliberately triggers no BRK and never ERETs.

The original local3472x4624 phone photo establishes both three-sample sequences
strictly increasing,49/97ticks across the two intervals,146totalticks each,
stable reported19,200,000Hz frequency andkind0/frame1/timerWrites0/verified1.
PhotoSHA2566dfeed19ac802cd88ddda789afb647d8ceb249084b104d255b9d5fd99d0b7b54.
Six absolute raw counter samples stay local; they are not an exact offset or
absolute frequency calibration. Timer IRQ remains the next separate gate.

[Cloud40924679614](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40924679614)
passed19steps,20new host tests and218 historical regression instances recorded
separately. Actual26-file FD/FV/PE/ELF/counter MRS/barrier/loop/zero-template
verification preceded ONE freshly seeded temporary boot. Exact CI source is
baf9ceb8a66dc26f6a66623f5f64acd62be1a299; subsequent closeout is docs only.
No partition flash/erase or automatic retry. Private image/seed/photo stay local.

It takes THREE ordered CNTPCT_EL0/CNTVCT_EL0 samples each, separated by TWO
fixed4096/8192-iteration loops. Every counter MRS has an immediately preceding
ISB. CNTFRQ_EL0 is read before/after:0<frequency<=1GHz and equal. Each unsigned
sequence must strictly increase; totaldelta must be positive and<reportedfreq.
Stalls, backwards/wrapped counts and large jumps reject; no poll-until-change.
Different virtual offsets and unequal physical/virtual deltas are allowed.
The frequency is firmware metadata, not an external calibration or exact
cross-counter-offset measurement. These rules follow
[Arm Generic Timer §4.1](https://documentation-service.arm.com/static/65fac6957bcc0c1c661b36c0).

Only the diagnostic's counter reads are added: no timer/GIC/MMIO programming,
DAIF unmask or IRQ is performed. Prior firmware timer configuration is outside
this claim. Higher-EL traps/fetch failure can prevent output; general recovery,
timer IRQ, scheduler and full XNU/iOS remain unverified.

New counter-three-sample-v1 record,36fields:
00kind,01detail/vector,02EL,03SCTLR,04VBAR,05ESR,06ELR,07rawFAR,08SP,09LR,
0ASPSel,0B/0Cfrequency pre/post,0D/0E/0Fphysical0/1/2,10physicaldelta,
11/12/13virtual0/1/2,14virtualdelta,15loop4096,16loop8192,17samplecount3,
18rawSPSR(exceptiononly),19TCR,1ATTBR0,1BTTBR1,1CMAIR,1Dheaderflags,
1Eheaderbase,1Fx0,20FP,21frameverified1,22timer-write-count0,23verified1.
Do not reuse stage14 field meanings. Eight bands pluskind0/verified1, the SIX
raw sample values, both deltas/frequencies and loop/sample metadata are the
hardware acceptance evidence. Normal ESR/ELR/FAR/SPSR are zero; an unexpected
exception captures its raw values withkind1 and no success.

Original208-byte frame/124-byte writes are checked before counter reads.
Legacy snapshot fields are cleared if pre-layout rejection occurs; live x0/FP
are then captured for diagnosis. Schema-ready and one-shot validated token
gate normal success; every vector rejects even with a token. Busy/nested or
failed record/frame/CTR proof halts MCIon; no unverified data access or DC.
All successful MCIoff paths clean originalframe and whole4Krecord first.

KernelSHA5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8,
patch offsets3f7290/3f733c/9e1e80,owneddiagnostic<=4096B. Display remains
8bands/36fields/704/pitch38/last1384/footer1440. The original XNU block maps
remain RWX; no final kernel W^X claim is made.

New20 host tests are distinct from218 prior regression instances. Host tests
explicitly model privileged registers, counters, AT/cache/SP banks; they do
not prove hardware progression. Verify actual FD/FV/PE/ELF/counter MRS/barriers
and zero-seed template, generate a fresh private OS seed and fastboot boot
ONCE. No flash/erase/retry; private image, seed, original photo stay local.

```
python -m unittest discover -s xnu-counter-checkpoint -v
```

Python3.12/Unicorn2.1.4/LLVM/Clang/LLD/C compiler, same pinned input environment
overrides as stage14. Logs grouped under local15-计数器递增.
