# K70 stage08 original bootstrap prefix checkpoint

This experiment runs the fixed kernel's original `__start` branch and all
564 bytes of its original `start_first_cpu` prefix. It stops at the original
`common_start` boundary, before that routine changes TCR/TTBR/MAIR or enables
the XNU mappings. Original prefix bytes are preserved and SHA256-verified.

The original prefix sets early architectural registers and stack addresses,
clears its 64 KiB bootstrap table pool, and builds its initial block tables.
The checkpoint checks register values and every one of the 8192 table entries.
It then records diagnostics and halts. This is **not** completed original CPU
initialization, `arm_init`, full XNU, iOS, or userland.

The constructed block maps cover `880000000..890000000`, while the owned
allocation covers `880004000..890004000`: 16 KiB precedes owned memory and the
last 16 KiB is omitted. **These tables are never enabled.** A later design must
resolve containment before allowing the original common initialization onward.
No access to the preceding physical pages is part of this experiment.

The only kernel RAM patches are the bounded checkpoint at `common_start` and
the first instruction of each of 16 low exception-vector slots. The transition
installs the same physical VBAR before branching, so an EL1 exception in the
first original instruction has a stack-free diagnostic route. Traps handled
above EL1 remain outside this diagnostic path. Exactly four
owned code pages become RO+X and are synchronized to the instruction side before
execution. Stage07 rollback, identity, cache-line and EBS policies are retained.

Expected bands: purple (transition), orange (MMU-off continuation), blue and
white (prefix register/table contract), **green** (new stage08 pass). Red in
rows 128–447 means captured exception or rejected contract. Every path halts;
Power + Volume Down returns to FASTBOOT.

Seventeen hexadecimal rows below the bands show the local RAM record:

| Row | Meaning |
| --- | --- |
| 00 | kind: 0 pass, 1 exception, 2 contract rejection |
| 01 | exception vector 0..15, or contract cause 1 registers / 2 table pool |
| 02 | CurrentEL (4 means EL1) |
| 03 | SCTLR_EL1 after transition |
| 04 | VBAR_EL1 |
| 05 | ESR_EL1, only meaningful for kind1 |
| 06 | ELR_EL1, only meaningful for kind1 |
| 07 | FAR_EL1, only meaningful for kind1 |
| 08 | selected SP, recorded without using stack memory |
| 09 | LR before any diagnostic subroutine call |
| 0A..10 | original x20..x26 |

All record stores and glyph reads are naturally aligned for MMU-off operation.
The display uses its own local hexadecimal glyph data and bounded 32-bit GOP
stores; there are no firmware services after successful ExitBootServices.
The pinned console has 36-pixel lines. An explicit form feed resets its private
cursor, then 40 blank lines place retained UEFI context at row1440, below the
diagnostic area's last row1321. Font/console sources are hash-checked; digits
also have a48-pixel left margin.

Host tests execute the actual original prefix and assembled diagnostics under
Unicorn 2.1.4. Registers/cache/DAIF/SPSel are explicit models, with accelerated
cache-loop first/last boundaries. Synthetic exception records prove routing and
display, not that a hardware exception has been observed. A new phone photo
with five bands and stage08 context is required before any hardware pass claim.

Use a fresh private seed per boot via reviewed `xnu-handoff-probe/seed_image.py`.
The public CI image is a zero-seed template. Seeded images, phone photos and raw
local evidence remain local in the central stage08 logs. Use `fastboot boot`
only; no flash, erase, disk, filesystem, SMP or partition changes are included.
