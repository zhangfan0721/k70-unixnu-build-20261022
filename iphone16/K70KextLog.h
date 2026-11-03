/* SPDX-License-Identifier: MIT
 * Display adapter for OSKext's existing formatted messages. Normal load context.
 * No allocation, new lock, formatter, or independent message store.
 */
#ifndef K70_KEXT_LOG_H
#define K70_KEXT_LOG_H
extern "C" int boot_progress_active(void);
extern "C" void boot_progress_stage(const char *);
extern "C" void k70_formal_cpu_trace(const char *, uint64_t);

static inline bool k70_kext_scope(OSKext *kext)
{
 if (!kext) return false;
 const char *id = kext->getIdentifierCString();
 return id && (!strcmp(id, "com.apple.iokit.IOStorageFamily") ||
     !strcmp(id, "com.apple.filesystems.hfs.kext") ||
     !strncmp(id, "com.apple.kpi.", 14));
}

static inline void k70_kext_visible(OSKext *kext, OSKextLogSpec spec,
    char *message, bool prefix_only)
{
 if (!boot_progress_active()) return;
 if (kext ? !k70_kext_scope(kext) :
     ((spec & kOSKextLogLevelMask) > kOSKextLogWarningLevel)) return;
 boot_progress_stage(kext ? kext->getIdentifierCString() : "OSKext global error");
 // The existing log lock owns this writable formatted buffer. Restore every
 // temporary terminator before the original user queue and printf consume it.
 unsigned used = 0, lines = 0;
 while (message[used] && used < 768 && lines < 16) {
  unsigned end = used;
  while (end - used < 48 && end < 768 && message[end] && message[end] != '\n') ++end;
  const char saved = message[end];
  message[end] = 0;
  boot_progress_stage(message + used);
  ++lines;
  message[end] = saved;
  used = end;
  if (saved == '\n') ++used;
 }
 if (message[used]) boot_progress_stage("OSKext message capped (16 lines/768 bytes)");
 if (prefix_only) boot_progress_stage("OSKext allocation failed; prefix only");
}

static inline void k70_kext_raw(OSKext *kext, const char *step, OSReturn result)
{
 if (!boot_progress_active() || !k70_kext_scope(kext)) return;
 boot_progress_stage(kext->getIdentifierCString());
 k70_formal_cpu_trace(step, (uint32_t)result);
}
#endif
