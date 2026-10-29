# K70 durable input implementation plan

> REQUIRED SUB-SKILL superpowers:executing-plans inline, with one fresh final reviewer.

Goal: restore exactly the previously tested kernel without expiring Actions downloads.
Architecture: preserved public ZIPs + bounded validating stdlib restorer + six workflow replacements + fast proof workflow.
Tech: Python3.12 unittest, ZIP/SHA-256, GitHubActions, clean Git clone.
Spec: ../specs/2026-10-29-pinned-inputs.md

## Global constraints

Keep3pinned SHA values from spec. No firmware or phone changes. No resets/cleans or unrelated files from old dirty checkout. No force-push, private data or seed uploads. Preserve131 prior firmware tests and later kernel hash assertions.

## Review focus

- Corrupt ZIP must reject before output, even if ZIP parser can read it.
- Traversal, duplicates, links, oversized expansion, wrong member set must reject.
- Existing output and wrong kernel/manifest must be preserved/rejected.
- All six workflows must consume exact restored kernel path and retain later hash assertions.
- Binary provenance and proof-run publication must not claim byte reproducibility or cloud success without evidence.

### Task1: Validating restorer

Files tools/restore_pinned_kernel.py,tools/test_restore_pinned_kernel.py.
Interface validate_archive(raw,zip_sha,kernel_sha)->dict of exact5members; restore(bundle,output)->report checks real pinned pair and calls validator. Tests may pass explicit fixture digests to pure validator; CLI cannot override.
- [x] RED missing validator/restore, run unittest discover -s tools -v; Expected assertion missing implementation.
- [x] Implement minimal bounded validation and exclusive fresh-directory output; GREEN all positive/corruption/path/member/manifest/output checks.
- [ ] Commit tool/tests, record tests and base.

### Task2: Preserved assets and six consumers

Files pinned-inputs/40518851995/*; six existing workflow files; README.md.
Consumes restore(bundle,output) fromTask1. Produces actual restored kernel-input/ and evidence/pinned-kernel-input.json.
- [x] Copy both known public ZIPs, record hashes/provenance; invoke CLI on actual bundle to a new central verification directory. Expected exact kernel SHA5fcfc61a... and5files.
- [x] Replace old download step only; validate YAML and each run script bash syntax. Expected6 replacements, no run-id download consumers, all later hashes retained.
- [ ] Update rootREADME and commit [skip ci].

### Task3: Proof, final review and publication

File .github/workflows/k70-pinned-input.yml; logs outputs/K70-阶段日志/11-构建输入持久化/准备.
- [x] Add quick Ubuntu workflow to test helper and restore real bundle, validate syntax and local commands.
- [ ] Final fresh reviewer of whole change; fix Important regressions RED→GREEN once, commit proof workflow separately.
- [ ] Authenticate only if required; compare remote, push maintenance tip then proof tip separately; verify remote files/ZIP hashes and successful proof run.
- [ ] Archive source/review/test/CI results, update central index and validate catalog.

## Ledger

- Task1 verification:16tests RED16missing-implementation assertions in0.023s, then16GREEN in1.055s. Logs central11/准备/restore-{red,green}.log. Known public ZIPs copied before tests as actual integration fixtures; asset copying moved ahead fromTask2, production code remained absent forRED. User preference keeps ledger/evidence centrally rather than a second scratch-log root.
- Task2 actualCLI restored5files and exactkernelSHA, report central11/准备/pinned-kernel-input.json. YAML7valid/bash44valid,6oldconsumersreplaced,alllaterkernelassertionsretained. Original toolhashes and oldfirmwaretests unchanged. No repeatedfirmwarebuild needed for local input-only change; cloud proof will exercise the actual preserved pair separately.

- Ruling: native managed-worktree tool rejects nested repository sourceRoot; use clean clone work/k70-next instead. Old checkout is untouched. Cost another small checkout, but history starts exactly at current remote main.
- Ruling: finish durable-input prerequisite as stage11 before original C-prologue work. Existing run would expire Nov3 and clean Git lacks publish credentials; make dependency repair concrete first. Cost deferring C code to subsequent stage.
- Ruling: use exact public ZIPs in Git instead of releases; avoids mutable asset lookup and keeps source-byte review simple. Cost about9.7MB checkout growth.
- Pre-flight interfaces: Task1CLI output kernel-input/ feeds Task2 unchanged hash checks; Task3proof runs Task1 and Task2 actual assets. No incompatible path found.
