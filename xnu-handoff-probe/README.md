# K70 no-jump handoff data hardware check

This isolated app allocates one complete256MiB window at0x880004000 before
materializing the fixed kernel and preparing the reviewed boot_args/AppleADT
inside that owned window. The same portable C validators run in host tests
and the app. Source/kernel hashes, memory bounds, single-CPU/GOP/GIC profile,
template hashes, field ranges, private seed transport and readback hashes
must all pass. No XNU entry, ExitBootServices, MMU/cache/GIC transition or
storage access is performed. On key exit the entire window is freed.

## Public artifact requires private local preparation

`K70-XNU-handoff-template.img` has an all-zero112-byte seed reservation.
It is deliberately NOT a ready-to-boot candidate. The application rejects
that unprepared seed. No private entropy is created or published by CI.

After separately verifying the downloaded artifact digest, manifest,
embedded app and FD/DTB/profile, prepare a NEW local image immediately before
each temporary boot:

```sh
python3 xnu-handoff-probe/seed_image.py inject --input /path/to/template.img \
  --expected-sha VERIFIED_TEMPLATE_SHA256 --out /new/local-boot.img \
  --report /new/local-seed-report.json
python3 xnu-handoff-probe/seed_image.py verify --input /new/local-boot.img
```

The injector requires the exact expected imageSHA, unchanged pinned kernel
envelope and zero seed reservation. It uses a fresh64-byte local PC OS seed,
modifies only the112 reserved bytes, and refuses repeated injection into an
already-prepared image. Never upload a privately prepared image or its seed.
The report and phone display contain only seed hashes for matching transport.
The firmware validates metadata, nonzero shape and SHA256 of the trailer;
these integrity checks alone do not establish randomness quality or freshness.
Freshness comes from performing this local generation before the current boot.

Keep the original firmware/kernel payload format and reserved source range;
the additional112 bytes follow the fixed envelope and are included in the
initrd bounds check. The original kernel parser still receives only the
unchanged pinned envelope length. Template_image/seed tooling checks boot
structure and seed patch mechanics; separate artifact proof must establish
firmware identity and contents.

## Evidence to photograph

- `MATERIALIZED SHA256 OK`
- `OWNED WINDOW 10000000 @ 880004000`
- `HOST SEED TRANSPORT SHA256 OK` and the seed hash prefix matching the local report
- boot_args PA881548000, ADT PA881549000, ADT KVAFFFFFFF008549000, top PA88154C000
- `BOOT_ARGS / ADT VERIFY OK`
- `HANDOFF DATA PASS - KERNEL JUMP DISABLED`

Even all these passes prove data ownership/preparation only. The eventual
entry executable attributes, cache/MMU/ExitBootServices sequence and a real
early-kernel checkpoint remain a separate milestone. A loader green bar is
not proof of reaching a kernel checkpoint.

Phone logs stay local. New evidence is grouped by run under
`outputs/K70-阶段日志/06-交接数据实机核验/` in the working session.
