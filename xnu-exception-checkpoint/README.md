# K70 controlled synchronous exception capture (stage14)

This probe established bounded real exception-entry evidence on the connected
K70 on2026-10-30. It retains the pinned stage13 original caller/empty RET and
stops before relocation, then deliberately executes one BRK #0x4B14 in owned
diagnostic code. A stack-free vector handler captures and verifies evidence,
cleans owned dirty data, disables MCI from physical instructions, renders and
halts. It never ERETs or resumes original C. A local original phone photo
established hardware success; host models and firmware builds alone cannot.

The photo shows8bands,00/01=0,05=F2004B14,06/19=FFFFFFF0086086C4,
SP1postFFFFFFF007C04000/SPSel1 versus SP0preFFFFFFF007BFBF30/SPSel0,
phase1B=2 and capture23=1. RawSPSR620003C4 masks to600003C4; bits outside
F00003DF are preserved in evidence and not asserted. RawFAR0 is not a valid
BRK fault address. The original3472x4624 photoSHA256 is
50a870cfcd475d319bbdb35c779459eb1ed96df2d1300fd43d5cee3af3e0f49a.

[Cloud40906124944](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40906124944)
passed19steps:20 new host checks and198 historical regression instances,
recorded separately. Actual26-file FD/FV/PE/ELF/opcode/vector/template checks
preceded one freshly seeded local temporary boot. The exact CI source was
1c57f0c59808e9ee711903af5c1a3bde5fb034b2; later closeout changes are docs only.
Private images, seed and original photo remain local. No flash/erase/retry.

Original firstCPU selects SP1 topFFFFFFF007C04000 and then SP0. C entry uses
SP0FFFFFFF007BFBF30. The expected same-EL synchronous vector is0; exception
entry selects SP1. Expected ESR isF2004B14, ELR is the BRK instruction's KVA,
postSPSel1 and postSPFFFFFFF007C04000. SPSR bitsF00003DF must match captured
preNZCV/DAIF/EL1t. FAR is recorded raw and has no fault-address validity for BRK.
These rules follow the linked [Arm exception model](https://documentation-service.arm.com/static/63a065c41d698c4dc521cb1c),
[BRK guide](https://documentation-service.arm.com/static/6245c734b059dc5ff9a8bdab)
and [FAR reference](https://developer.arm.com/documentation/102670/0300/AArch64-registers/AArch64-register-descriptions/AArch64-Generic-System-control-register-description/FAR-EL1--Fault-Address-Register--EL1-).

This is a new, explicitly labelled36-field record:00kind,01vector/detail,
02postEL,03postSCTLR,04postVBAR,05ESR,06ELR,07rawFAR,08postSP,09LR,0ASPSR,
0BpostSPSel,0CpreSP,0DpreSPSel,0EpreEL,0FpreSCTLR,10preVBAR,11/12TCR,
13/14TTBR0,15/16TTBR1,17/18MAIR pre/post,19expectedBRKPC,1AexpectedESR,
1Bphase2verified,1Cpreflags,1Dpreheaderbase,1E/1Fx0,20/21FP pre/post,
22BRK-FAR-valid0,23captureverified1. Eight success bands plus00=0/23=1 and
the actual syndrome/PC/SP evidence identify the expected-capture result.
The rendering bounds remain704/pitch38/last1384, context1440.

All original saved registers, guard/zero stores and208-byte frame are verified
before arming; original writes remain124bytes. The one-shot token is consumed,
busy entry prevents nested capture, and a skipped BRK takes an explicit failure
path. Wrong syndrome, PC, mode, vector, SP or unarmed exceptions cannot PASS.
The handler performs no stack data access. Record translation failures now
halt with MCI enabled: the pre-exception record can already contain dirty data.
Both record/frame mappings and16..4096-byte cache geometry must validate before
any DC or MCIoff; invalid mapping/geometry halts without new success colors.

KernelSHA5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8,
patch offsets3f7290/3f733c/9e1e80,16vector words and8UEFI ROX pages remain
fixed. Prior stages remain unchanged. Original XNU block maps remain RWX;
this probe does not establish final kernel W^X or general exception recovery.
Higher-EL debug routing, unavailable code fetch and arbitrary mapping damage
can prevent output. Timer counter progression and timer IRQ are later gates.

Host tests explicitly model BRK decode, system state and SP banks; they are
separate from actual hardware exception evidence.198 prior regression cases
remain in cloud checks, with new probe tests counted separately. Independently
verify actual FD/FV/PE/native ELF/BRK opcode/vector and zero-seed template,
generate a fresh private local OS random seed, and use fastboot boot once.
Private image and photo stay local. No partition flash/erase. Power+VolDown
returns to FASTBOOT after the intentional halt.

```
python -m unittest discover -s xnu-exception-checkpoint -v
```

Requires Python3.12, Unicorn2.1.4, LLVM/Clang/LLD and a C compiler; pinned input
environment overrides match stage13.
