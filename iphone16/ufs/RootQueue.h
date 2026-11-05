// SPDX-License-Identifier: BSD-2-Clause-Patent
// Root queue takeover; shared with the host fault-injection harness.
static bool hostWaitRegister (unsigned offset, uint32_t mask, uint32_t value)
{
  uint64_t deadline;
  clock_interval_to_deadline (100, kMillisecondScale, &deadline);
  do {
    if ((read32 (gHost.hc, offset) & mask) == value) return true;
    IODelay (10);
  } while (mach_absolute_time () < deadline);
  return false;
}

static bool hostQueueIdleStopped(void) {
  return (read32(gHost.hc,0x34)&1) && (read32(gHost.hc,0x30)&15)==15 &&
         !read32(gHost.hc,0x58) && !read32(gHost.hc,0x78) &&
         !(read32(gHost.hc,0x60)&1) && !(read32(gHost.hc,0x80)&1) &&
         !(read32(gHost.hc,0x20)&kUfsFatalStatus) && hostControlHealthy();
}
static bool hostStopQueue (const char **why)
{
  // Confirm the firmware has no active transfer/task before changing its
  // request list or the storage stream's SMMU routing.
  if (!(read32 (gHost.hc, 0x34) & 1) || (read32 (gHost.hc, 0x30) & 0x0f) != 0x0f) {
    recordTransport (kIOReturnNotReady, 15);
    *why = "controller not ready for takeover";
    return false;
  }
  if (read32 (gHost.hc, 0x58) || read32 (gHost.hc, 0x78)) {
    recordTransport (kIOReturnBusy, 15);
    *why = "firmware request outstanding";
    return false;
  }
  if (read32 (gHost.hc, 0x20) & kUfsFatalStatus) {
    recordTransport (kIOReturnIOError, 15);
    *why = "firmware controller error";
    return false;
  }
  if(!hostControlHealthy() || (read32(gHost.hc,0x80)&1)) {
    *why="task list enabled or MMIO unhealthy";return false;
  }
  hostWrite (0x24, 0);
  if(!hostControlHealthy() || read32(gHost.hc,0x24)!=0) {
    *why="interrupt mask readback";return false;
  }
  hostWrite (0x60, 0);
  if (!hostControlHealthy() || !hostWaitRegister (0x60, 1, 0)) {
    recordTransport (kIOReturnTimeout, 15);
    *why = "request list stop";
    return false;
  }
  if(!hostQueueIdleStopped()){*why="post-stop queue changed";return false;}
  return true;
}

static bool hostStartQueue (const char **why)
{
  uint64_t limit=(read32(gHost.hc,0)&0x01000000U)?(1ULL<<36):(1ULL<<32);
  if(!hostQueueIdleStopped() || !k70DmaAllocation(gHost.phys,kDmaBytes,limit)) {
    *why="queue/DMA changed before start";return false;
  }
  hostWrite (0x50, static_cast<uint32_t> (gHost.phys));
  if(!hostControlHealthy()){*why="UTRL low address write";return false;}
  hostWrite (0x54, static_cast<uint32_t> (gHost.phys >> 32));
  if (!hostControlHealthy() || read32 (gHost.hc, 0x50) != uint32_t (gHost.phys) ||
      read32 (gHost.hc, 0x54) != uint32_t (gHost.phys >> 32)) {
    recordTransport (kIOReturnIOError, 15);
    gHost.poisoned=true;
    *why = "request list address";
    return false;
  }
  gRootDiagnostic.isBefore = read32 (gHost.hc, 0x20);
  hostWrite (0x20, 1);
  if(!hostControlHealthy()){*why="status acknowledgement";return false;}
  hostWrite (0x60, 1);
  if (!hostControlHealthy() || !hostWaitRegister (0x60, 1, 1) || !hostWaitRegister (0x30, 3, 3)) {
    recordTransport (kIOReturnTimeout, 15);
    gHost.poisoned=true;
    *why = "request list ready";
    return false;
  }
  return true;
}
