#include "WindowPlan.h"
static unsigned errors;
static void expect(bool ok){if(!ok)++errors;}

extern "C" unsigned k70_ufs_window_test() {
  using namespace K70Window;
  Extent e{211008ULL, 2359296U};          // 9 GiB / 4 KiB

  // Bounds: offset is window relative, so the first and last block are inside
  // and nothing outside the declared extent is, nor is an empty request.
  expect(inside(e, 0, 4096));
  expect(inside(e, e.bytes() - 4096, 4096));
  expect(inside(e, e.bytes(), 1) == false);
  expect(inside(e, e.bytes() - 1, 1));
  expect(!inside(e, e.bytes() - 1, 2));   // one byte past the end
  expect(!inside(e, 0, 0));
  expect(!inside(Extent{0, 0}, 0, 1));    // unset extent
  Extent wrap{~0ULL, 2};
  expect(!inside(wrap, 0, 1));            // base+blocks overflow refused
  expect(!inside(e, ~0ULL, 1));           // offset overflow refused

  // An aligned request reads straight through, no bounce.
  Plan p{};
  expect(make(e, 0, 131072, &p) && !p.bounce);
  expect(p.aligned == 0 && p.span == 131072 && p.head == 0 && p.tail == 0);
  expect(p.count == 1 && p.chunk[0].lba == e.base && p.chunk[0].bytes == 131072);

  // Larger than one data buffer: split at exactly 32 blocks, never straddling.
  expect(make(e, 0, 131072 + 4096, &p) && !p.bounce);
  expect(p.count == 2);
  expect(p.chunk[0].bytes == 131072 && p.chunk[1].bytes == 4096);
  expect(p.chunk[1].lba == e.base + 32);
  expect(p.chunk[0].lba == e.base);

  // Coverage: chunks are contiguous, block aligned and sum to the span.
  unsigned long long covered = 0;
  for (unsigned i = 0; i < p.count; ++i) {
    expect(p.chunk[i].bytes % kBlockBytes == 0);
    expect(p.chunk[i].bytes <= kMaxTransfer * kBlockBytes);
    expect(p.chunk[i].offset == p.aligned + covered);
    covered += p.chunk[i].bytes;
  }
  expect(covered == p.span);

  // Unaligned request: bounce, and the plan still covers whole blocks.
  expect(make(e, 100, 4096, &p) && p.bounce);
  expect(p.aligned == 0 && p.span == 8192 && p.head == 100 && p.tail == 3996);
  expect(p.count == 1);

  // Request of exactly one block spanning a chunk boundary.
  expect(make(e, 4096, 4096, &p) && !p.bounce && p.count == 1);
  expect(p.chunk[0].lba == e.base + 1);

  // Refusals keep the plan untouched.
  Plan bad{};
  bad.count = 77;
  expect(!make(e, e.bytes() - 10, 4096, &bad));
  expect(bad.count == 0);

  // A single request may not exceed the transfer plan's own ceiling.
  expect(!make(e, 0, (unsigned long long)kMaxChunks * kMaxTransfer * kBlockBytes + 4096, &bad));
  expect(make(e, 0, (unsigned long long)kMaxChunks * kMaxTransfer * kBlockBytes, &p));
  expect(p.count == kMaxChunks);

  // The window is a read-only projection; no range is ever writable.
  expect(!writable(0, 4096));
  expect(!writable(e.base, 1));

  // Boot-argument parsing: hex, decimal, spaces, and every refusal.
  unsigned long long b = 1;
  unsigned n = 1;
  expect(parseArgument("0x33840,0x240000", &b, &n) && b == 211008 && n == 2359296);
  expect(parseArgument(" 0X33840 , 0x240000 ", &b, &n) && b == 211008 && n == 2359296);
  expect(parseArgument("211008,2359296", &b, &n) && b == 211008 && n == 2359296);
  expect(!parseArgument("", &b, &n));
  expect(!parseArgument(nullptr, &b, &n));
  expect(!parseArgument("0x211008", &b, &n));          // no separator
  expect(!parseArgument("0x211008,", &b, &n));         // no block count
  expect(!parseArgument("0x211008,0", &b, &n));        // zero block count
  expect(!parseArgument("0x211008,0x0", &b, &n));
  expect(!parseArgument("0x211008,0x240000junk", &b, &n));
  expect(!parseArgument("0xg11008,0x240000", &b, &n)); // bad digit
  expect(!parseArgument("0x211008,0x123456789", &b, &n)); // > 32 bits
  expect(!parseArgument("0xffffffffffffffff0,1", &b, &n)); // base overflow
  // A refused argument must not modify either output.
  b = 7; n = 9;
  expect(!parseArgument("0x211008,0x0", &b, &n) && b == 7 && n == 9);
  return errors;
}

#ifdef K70_WINDOW_MAIN
#include <cstdio>
int main(){unsigned e=k70_ufs_window_test();std::printf("k70 window: %u errors\n",e);return e?1:0;}
#endif
