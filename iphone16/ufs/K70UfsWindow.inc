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
  // Prove the declared window is actually readable before it becomes a root.
  if (hostRead4k (kWindowLun, lba, 1, gWindowScratch) != kIOReturnSuccess) {
    gWindowState = 2;
    return false;
  }
  gWindowDev = mdevadd_fetch (devid, blocks, k70WindowFetch);
  if (gWindowDev < 0) {
    return false;
  }
  gWindowState = 1;
  return true;
}
