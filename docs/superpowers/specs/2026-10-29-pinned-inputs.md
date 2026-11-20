# K70 durable pinned kernel input

Intent: remove the six checkpoint workflows' dependency on expiring Actions run40518851995 while keeping the exact already-tested kernel. Preserve old dirty work/k70-build unchanged; implementation is in clean clone work/k70-next, branch k70-c-prologue at a80f1715.

Existing user delegation covers reversible work, reviewed publication and temporary boots. No repeat design/branch/publish questions. This plan is the prerequisite to the next original C-prologue checkpoint; it changes no firmware code and needs no phone operation.

Approach chosen: keep both original public artifact ZIPs in Git under pinned-inputs/40518851995; restore locally using Python stdlib with exact SHA-256 validation. Cost about9.7MB per checkout. Alternatives: a release asset requires another publishing/upload path and mutable release maintenance; extending artifact retention still expires; rebuilding on macos-15 does not prove byte reproducibility. Keeping original bytes is preservation, not a claim of reproducible compilation.

Pinned platform ZIP SHA215eb74ed6742bd1c3705501f2d4091de717e76dd2fff290737ba64aa1ecb2f7; evidence ZIP SHAf5d8b0ab758dd6d09a42ccd174ec4a27edbbe00c36818a0929523bba11e45046; kernel SHA5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8. Both ZIPs are already public build outputs and contain no private seed or device data.

Restore contract: validate both ZIP hashes before output; platform ZIP has exactly5 regular unique members(SHA256SUMS,build-report.json,crypto-hmac.json,kernel.development.vermeer-build.macho,symbols.txt), no encryption/symlinks/path escape; total uncompressed size<=32MiB. Check kernel digest and exact manifest. Reject existing destination, preserve input/output on validation failure. CLI has no hash override. On success emit source-run/platform/evidence/kernel SHA and restored-file count as JSON.

Workflow interface: replace only old download step in6workflows with tools/restore_pinned_kernel.py --output kernel-input, storing JSON under evidence/. Keep all later kernel hash checks and firmware/test/build steps. Add a fast proof workflow exercising restore tests and actual preserved assets. Root README explains stage10 hardware boundary, durable input and private-image rules.

Publication: one reviewed maintenance push with [skip ci] avoids6 redundant firmware builds; a separate push adds proof workflow and runs only its fast validation. GitHub documents that skip applies to push/PR and not dispatch: https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs . No bypass of required branch checks. Never force-push. Compare current remote main before publishing. Authentication currently missing in local Git; finish reviewable work before requesting required sign-in.

Acceptance: meaningful RED→GREEN archive corruption/safety/output-preservation tests; actual two-ZIP/kernel SHA proof;6workflow syntax and exact replacement check; fresh final review; no old checkout mutation; publish/proof run when authentication available; central stage11 logs. Source or CI authentication failure is reported accurately, not claimed fixed.
