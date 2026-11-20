# K70 original C prologue checkpoint (stage12)

Research diagnostic for Redmi K70/vermeer. It runs the exact original 60-byte arm_init prologue, then replaces its first BL with a branch to an owned diagnostic. The first helper, platform initialization, scheduler, storage and userland do not run. Stage10 established virtual entry; the separately verified stage12 hardware result is recorded below.

Hardware result (2026-10-29): this stage passed on the connected K70 after
run40846393171 and independent actual-artifact verification. The supplied photo
shows all eight bands, kind/cause0, SP/FP as specified below and frame-check21=1.
Only one freshly seeded temporary boot was used. Photo/private image stay local.

The pinned kernel SHA256 is `5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8`. Only offsets `3f7290`, `3f733c`, `9e1e70` and the first word of 16 low vectors change. Original firstCPU prefix, TTBR helper, cold common_start tail and all 60 prologue bytes are independently preserved. The original guard slot at VA `FFFFFFF007B3C268` / PA `880B3C268` contains zero. Observing this uninitialized slot does not establish guard initialization or OS security.

The prologue allocates 208 stack bytes and writes exactly 124: twelve saved registers, an eight-byte guard, sixteen zero bytes and four zero bytes. Other frame bytes remain unchanged. common_start sets x19 to its return address before C; the gate snapshots that expected save value and old FP. New SP is `FFFFFFF007BFBF30`, FP is `FFFFFFF007BFBFF0`, and x0/x19 must equal boot_args VA `FFFFFFF008548000`. Successful frame validation sets field21=1. The original frame remains in owned RAM until reset; it is not rolled back or resumed.

Allocation/ownership, bounded ExitBootServices, seven ROX pages, fixed guard and bootstrap maps are retained from reviewed stages09/10. All MCI-off diagnostic paths first reach owned physical instructions and clean the verified stack-frame cache lines, including emergency record-translation rejection and EL1 vectors. Failed frame translation, redirected PA or unsupported cache-line size halts with MCI still enabled, without unsafe cache operations or new success colors. Higher-EL traps, unavailable instruction fetch and arbitrary mapping corruption can still prevent diagnostics; host models do not guarantee hardware recovery.

Eight success bands add yellow at rows576..639. Fields00..21 use two columns of17, starting row704; their final glyph ends at1378, below the retained UEFI context at1440. Fields00..1F retain previous meanings;20 is FP and21 is the frame-check flag. Kind00=0 plus yellow and21=1 means this bounded checkpoint passed. Red is rejection/EL1 exception. Photo values are required: fastboot OKAY alone is not proof of execution.

Tests execute original instructions through the patched first-call location with shared physical/KVA backing and an exact original-write whitelist. AT/PAR, privileged registers, caches, DAIF and SPSel are explicit models. Exception injection covers each of nine original store-instruction boundaries, including every partially completed prologue, rather than pretending an asynchronous exception occurs between two callbacks of one STP.

Use GitHub Actions, verify actual FD/FV/PE against native ELF and pinned inputs, then generate a fresh private OS CSPRNG seed for each single temporary boot. Use `fastboot boot` only. Private seeded images and phone data stay local. Power+VolDown returns to FASTBOOT after the checkpoint halt.

```
python -m unittest discover -s xnu-c-prologue-checkpoint -v
```

Requires Python3.12, Unicorn2.1.4, Clang/LLD/LLVM and a C compiler. Set K70_KERNEL/K70_UEFI_SOURCE/K70_DTB to the pinned inputs outside this research workspace.
