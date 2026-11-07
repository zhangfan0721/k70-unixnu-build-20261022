// SPDX-License-Identifier: MIT
// A declared, read-only window served on demand through the qualified transport.
//
// This file is included from K70UfsTransport.inc inside its anonymous namespace,
// after ReadOnlyCommands.inc, so it reuses gHost and hostRead4k directly and
// issues no MMIO of its own. The window is never discovered: the caller declares
// an LBA extent, the policy records it, and every request is checked against it
// before a command is built.

static constexpr uint8_t kWindowLun = 0;
static volatile int gWindowState = 0;            // 0 closed, 1 open, 2 poisoned
static K70Window::Extent gWindowExtent = { 0, 0 };
static IOBufferMemoryDescriptor *gWindowBounce = nullptr;
static void *gWindowScratch = nullptr;
static dev_t gWindowDev = -1;

// Serves one strategy request. Returns an errno; the caller completes the buf.
// Any transport or policy failure poisons the window for good: a half-served
// root volume is worse than a device that stops answering.
static int k70WindowFetch (int devid, uint64_t offset, void *dst, size_t length)
{
  if (devid != 0 || gWindowState != 1 || !gWindowScratch || !dst || !length) {
    return EIO;
  }
  if (!gHost.ready || gHost.poisoned) {
    gWindowState = 2;
    return EIO;
  }
  const int served = K70Window::serve (gWindowExtent, offset, length, dst,
      gWindowScratch,
      [] (unsigned long long lba, unsigned blocks, void *target) -> int {
        return hostRead4k (kWindowLun, lba, blocks, target) == kIOReturnSuccess
            ? 0 : -1;
      },
      [] (unsigned long long lba, unsigned blocks) -> bool {
        return K70Window::declared ().inside (lba, blocks);
      });
  if (served == K70Window::kServed) {
    return 0;
  }
  if (served == K70Window::kRefused) {
    return EINVAL;                 // a bad request, not a broken device
  }
  gWindowState = 2;                // poison: never retry a half-served root
  return EIO;
}

// Hashes the first 512 KiB of the window and traces four 64-bit words. A
// hardware run can then be checked against a hash recorded from the same
// region before this code existed, so a correct read is a visible result and
// not an inference.
static void k70WindowReportHead (void)
{
  const uint64_t chunk = (uint64_t) K70Window::kMaxTransfer * K70Window::kBlockBytes;
  uint64_t total = gWindowExtent.bytes ();
  if (total > 524288) {
    total = 524288;
  }
  SHA256_CTX context;
  SHA256_Init (&context);
  for (uint64_t done = 0; done < total; done += chunk) {
    const uint64_t left = total - done;
    const uint32_t bytes = left > chunk ? static_cast<uint32_t> (chunk)
                                        : static_cast<uint32_t> (left);
    const uint32_t blocks = bytes / K70Window::kBlockBytes;
    if (!blocks) {
      break;
    }
    const uint64_t lba = gWindowExtent.base + done / K70Window::kBlockBytes;
    if (hostRead4k (kWindowLun, lba, blocks, gWindowScratch) != kIOReturnSuccess) {
      gWindowState = 2;
      return;
    }
    SHA256_Update (&context, gWindowScratch, blocks * K70Window::kBlockBytes);
  }
  uint8_t digest[32];
  SHA256_Final (digest, &context);
  for (unsigned word = 0; word < 4; ++word) {
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) {
      value = (value << 8) | digest[word * 8 + i];
    }
    k70_formal_cpu_trace ("UFS window head digest", value);
  }
}

// Declares the extent, proves one bounded read, then publishes md<devid>.
static bool k70WindowOpen (uint64_t lba, uint32_t blocks, int devid)
{
  if (gWindowState != 0 || !blocks) {
    return false;
  }
  if (!K70Window::declared ().declare (lba, blocks)) {
    return false;
  }
  gWindowBounce = IOBufferMemoryDescriptor::withCapacity (
      K70Window::kMaxTransfer * K70Window::kBlockBytes, kIODirectionIn);
  if (!gWindowBounce) {
    return false;
  }
  gWindowScratch = gWindowBounce->getBytesNoCopy ();
  if (!gWindowScratch) {
    return false;
  }
  gWindowExtent.base = lba;
  gWindowExtent.blocks = blocks;
  // Prove the declared window is actually readable, and leave a checkable hash
  // behind, before it becomes a root device.
  k70WindowReportHead ();
  if (gWindowState != 0) {
    return false;
  }
  gWindowDev = mdevadd_fetch (devid, blocks, k70WindowFetch);
  if (gWindowDev < 0) {
    return false;
  }
  gWindowState = 1;
  return true;
}
