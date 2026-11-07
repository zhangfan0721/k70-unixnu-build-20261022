// SPDX-License-Identifier: MIT
// A declared, read-only window served on demand through the qualified transport.
//
// This file is included from K70UfsTransport.inc inside its anonymous namespace,
// after ReadOnlyCommands.inc, so it reuses gHost and hostRead4k directly and
// issues no MMIO of its own. The window is never discovered: the caller declares
// an LBA extent, the policy records it, and every request is checked against it
// before a command is built.
#include "WindowPlan.h"
#include "ReadOnlyPolicy.h"

static constexpr uint8_t kWindowLun = 0;
static volatile int gWindowState = 0;            // 0 closed, 1 open, 2 poisoned
static K70Window::Extent gWindowExtent = { 0, 0 };
static IOBufferMemoryDescriptor *gWindowBounce = nullptr;
static void *gWindowScratch = nullptr;
static dev_t gWindowDev = -1;

extern "C" dev_t mdevadd_fetch (int devid, unsigned int size,
    int (*fetch) (int, uint64_t, void *, size_t));

// Serves one strategy request. Returns an errno; the caller completes the buf.
// Any transport or policy failure poisons the window for good: a half-served
// root volume is worse than a device that stops answering.
static int k70WindowFetch (int devid, uint64_t offset, void *dst, size_t length)
{
  if (devid != 0 || gWindowState != 1 || !gWindowScratch || !dst || !length) {
    return EIO;
  }
  K70Window::Plan plan;
  if (!K70Window::make (gWindowExtent, offset, length, &plan)) {
    return EINVAL;
  }
  if (!gHost.ready || gHost.poisoned) {
    gWindowState = 2;
    return EIO;
  }
  for (unsigned i = 0; i < plan.count; ++i) {
    const K70Window::Chunk &c = plan.chunk[i];
    const unsigned blocks = c.bytes / K70Window::kBlockBytes;
    if (!K70UfsPolicy::range (c.lba, blocks)) {
      gWindowState = 2;
      return EIO;
    }
    IOReturn status;
    if (plan.bounce) {
      status = hostRead4k (kWindowLun, c.lba, blocks, gWindowScratch);
    } else {
      status = hostRead4k (kWindowLun, c.lba, blocks,
          static_cast<uint8_t *> (dst) + (c.offset - plan.aligned));
    }
    if (status != kIOReturnSuccess) {
      gWindowState = 2;
      return EIO;
    }
    if (plan.bounce) {
      const uint64_t chunkStart = c.offset, chunkEnd = c.offset + c.bytes;
      const uint64_t reqStart = offset, reqEnd = offset + length;
      const uint64_t from = chunkStart > reqStart ? chunkStart : reqStart;
      const uint64_t to = chunkEnd < reqEnd ? chunkEnd : reqEnd;
      if (from < to) {
        memcpy (static_cast<uint8_t *> (dst) + (from - reqStart),
                static_cast<uint8_t *> (gWindowScratch) + (from - chunkStart),
                static_cast<size_t> (to - from));
      }
    }
  }
  return 0;
}

// Declares the extent, proves one bounded read, then publishes md<devid>.
static bool k70WindowOpen (uint64_t lba, uint32_t blocks, int devid)
{
  if (gWindowState != 0 || !blocks) {
    return false;
  }
  if (!K70UfsPolicy::window ().declare (lba, blocks)) {
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
