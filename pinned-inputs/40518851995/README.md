# Preserved input from run 40518851995

These two ZIPs preserve the original public GitHub Actions artifacts from
[source kernel run 40518851995](https://github.com/zhangfan0721/k70-unixnu-build-20261022/actions/runs/40518851995),
source commit `8a0aa65b425593985be5b9b05e5bd72620cebb36`.
They are the exact downloaded ZIP bytes, not newly compiled replacements.

| Git file | Original artifact | SHA-256 |
| --- | --- | --- |
| platform.zip | k70-source-platform-40518851995-1, ID12740598615, 7,424,990 bytes | 215eb74ed6742bd1c3705501f2d4091de717e76dd2fff290737ba64aa1ecb2f7 |
| evidence.zip | k70-source-evidence-40518851995-1, ID12741471384, 2,270,696 bytes | f5d8b0ab758dd6d09a42ccd174ec4a27edbbe00c36818a0929523bba11e45046 |

Both hashes were compared to GitHub's artifact API digest on 2026-10-29.
The original cloud artifacts expire on 2026-11-03; these Git files are retained
with the repository revision. No device data or private boot seeds are included.

Restore with `python tools/restore_pinned_kernel.py --output kernel-input` from
the repository root. The tool checks both ZIP hashes, exact platform members,
bounded expansion, the original SHA256SUMS and the kernel SHA-256
`5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8`.
An existing output directory is rejected. The evidence ZIP is hashed and
preserved without extracting it into the kernel directory.

This preserves the already tested input. Byte-for-byte reproducible compilation
on a future macOS runner has not been established. The original build report,
symbols, source patches and toolchain logs remain in the two original archives.
