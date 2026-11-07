// SPDX-License-Identifier: MIT
#pragma once
// Demand-fetched read-only window geometry.
//
// The window is declared, never discovered: an explicit LBA extent plus a block
// count. Every request is checked against that extent before a command reaches
// the controller, and each request is split into transfers no larger than one
// PRDT-sized data buffer. This header is deliberately pure so the same rules run
// in the host harness and in the kernel.
namespace K70Window {
enum : unsigned {
  kBlockBytes  = 4096,   // LUN0 4 KiB sectors, fixed by the route record
  kMaxTransfer = 32,     // blocks per command: kDataMax / kBlockBytes
  kMaxChunks   = 64,     // 64 * 32 blocks = 8 MiB of window per request
};

struct Extent {
  unsigned long long base;    // first authorized LBA
  unsigned blocks;            // authorized block count, non-zero when valid
  bool valid() const { return blocks != 0; }
  unsigned long long bytes() const {
    return (unsigned long long)blocks * kBlockBytes;
  }
};

struct Chunk {
  unsigned long long offset;  // byte offset inside the window
  unsigned bytes;             // always a whole number of blocks
  unsigned long long lba;     // absolute LBA for the command
};

struct Plan {
  unsigned count;
  Chunk chunk[kMaxChunks];
  unsigned long long aligned;   // block-aligned start of the transfer span
  unsigned long long span;      // covered bytes, block aligned
  unsigned long long head;      // offset - aligned, 0..4095
  unsigned long long tail;      // span - head - requested bytes
  bool bounce;                  // true when the request is not block aligned
};

// A byte range is servable only when it is non-empty and wholly inside the
// declared extent. Overflow of base+blocks is rejected rather than wrapped.
inline bool inside(const Extent &e, unsigned long long offset,
                   unsigned long long bytes) {
  if (!e.valid() || bytes == 0) return false;
  unsigned long long limit = e.bytes();
  if (e.base > ~0ULL - e.blocks) return false;
  return offset < limit && bytes <= limit - offset;
}

inline bool make(const Extent &e, unsigned long long offset,
                 unsigned long long bytes, Plan *plan) {
  if (!plan) return false;
  plan->count = 0;
  if (!inside(e, offset, bytes)) return false;
  unsigned long long aligned = offset & ~(unsigned long long)(kBlockBytes - 1);
  unsigned long long end = offset + bytes;
  unsigned long long spanEnd =
      (end + kBlockBytes - 1) & ~(unsigned long long)(kBlockBytes - 1);
  unsigned long long span = spanEnd - aligned;
  if (span > (unsigned long long)kMaxChunks * kMaxTransfer * kBlockBytes) {
    return false;
  }
  if (e.base > ~0ULL - (aligned + span) / kBlockBytes) return false;
  plan->aligned = aligned;
  plan->span = span;
  plan->head = offset - aligned;
  plan->tail = span - plan->head - bytes;
  plan->bounce = (plan->head != 0) || (plan->tail != 0);
  unsigned long long cursor = 0;
  while (cursor < span) {
    unsigned long long left = span - cursor;
    unsigned blocks = (unsigned)(left / kBlockBytes);
    if (blocks > kMaxTransfer) blocks = kMaxTransfer;
    if (plan->count >= kMaxChunks) return false;
    Chunk &c = plan->chunk[plan->count++];
    c.offset = aligned + cursor;
    c.bytes = blocks * kBlockBytes;
    c.lba = e.base + c.offset / kBlockBytes;
    cursor += c.bytes;
  }
  return plan->count != 0;
}

// Writes are never servable: the window is a read-only projection.
inline bool writable(unsigned long long, unsigned long long) { return false; }

// Parses one number for the declared window, refusing overflow before it can
// wrap. A "0x" prefix selects hexadecimal; otherwise the field is decimal.
inline bool parseNumber(const char *&text, unsigned long long limit,
                        unsigned long long *out) {
  const bool hex = (text[0] == '0' && (text[1] == 'x' || text[1] == 'X'));
  const unsigned radix = hex ? 16U : 10U;
  if (hex) text += 2;
  unsigned long long value = 0;
  unsigned digits = 0;
  while (*text && *text != ',' && *text != ' ') {
    const char c = *text;
    unsigned d;
    if (c >= '0' && c <= '9') d = unsigned(c - '0');
    else if (c >= 'a' && c <= 'f') d = unsigned(c - 'a') + 10U;
    else if (c >= 'A' && c <= 'F') d = unsigned(c - 'A') + 10U;
    else return false;
    if (d >= radix) return false;
    if (value > (limit - d) / radix) return false;
    value = value * radix + d;
    ++digits;
    ++text;
  }
  if (!digits) return false;
  *out = value;
  return true;
}

// Parses "0x<base-lba>,0x<blocks>" (or the same pair in decimal). Trailing
// garbage, a zero block count and any overflow are refused, so a malformed boot
// argument cannot widen the readable range silently.
inline bool parseArgument(const char *text, unsigned long long *base,
                          unsigned *blocks) {
  if (!text || !base || !blocks) return false;
  while (*text == ' ') ++text;
  unsigned long long first = 0, second = 0;
  if (!parseNumber(text, ~0ULL, &first)) return false;
  while (*text == ' ') ++text;
  if (*text != ',') return false;
  ++text;
  while (*text == ' ') ++text;
  if (!parseNumber(text, 0xffffffffULL, &second)) return false;
  while (*text == ' ') ++text;
  if (*text) return false;
  if (!second) return false;
  *base = first;
  *blocks = unsigned(second);
  return true;
}

}
