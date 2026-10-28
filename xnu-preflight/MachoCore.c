// SPDX-License-Identifier: BSD-2-Clause-Patent
// No firmware calls: this exact parser/materializer also runs in host tests.
#include "MachoCore.h"

static K70_U32 R32(const K70_U8 *P) {
  return (K70_U32)P[0] | ((K70_U32)P[1] << 8) |
         ((K70_U32)P[2] << 16) | ((K70_U32)P[3] << 24);
}
static K70_U64 R64(const K70_U8 *P) {
  return R32(P) | ((K70_U64)R32(P + 4) << 32);
}
static int Overlap(K70_U64 A, K70_U64 N, K70_U64 B, K70_U64 M) {
  return N && M && A < B + M && B < A + N;
}

int K70ParseMachO(const K70_U8 *Data, K70_SIZE Size, K70_PLAN *Plan) {
  K70_U32 Commands, CommandBytes, I, J, ThreadCount = 0;
  K70_SIZE At, End;
  K70_U64 Low = ~(K70_U64)0, High = 0, Pc = 0;
  if (!Data || !Plan || Size < 32 || Size > K70_MAX_BYTES) return K70_BAD_HEADER;
  if (R32(Data) != 0xFEEDFACF || R32(Data + 4) != 0x0100000C ||
      R32(Data + 8) != 0 || R32(Data + 12) != 2 || R32(Data + 28) != 0)
    return K70_BAD_HEADER;
  Commands = R32(Data + 16); CommandBytes = R32(Data + 20);
  if (!Commands || Commands > 128 || CommandBytes > Size - 32 ||
      CommandBytes < Commands * 8) return K70_BAD_COMMAND;
  At = 32; End = 32 + CommandBytes; Plan->Count = 0;
  for (I = 0; I < Commands; I++) {
    K70_U32 Cmd, Bytes;
    if (At > End || End - At < 8) return K70_BAD_COMMAND;
    Cmd = R32(Data + At); Bytes = R32(Data + At + 4);
    if (Bytes < 8 || (Bytes & 7) || Bytes > End - At) return K70_BAD_COMMAND;
    if (Cmd == 0x19) {
      K70_U64 Va, Memory, File, FileBytes;
      K70_U32 Sections, Maximum, Initial;
      K70_SEGMENT *S;
      if (Bytes < 72) return K70_BAD_SEGMENT;
      Sections = R32(Data + At + 64);
      if (Sections > (Bytes - 72) / 80 || Bytes != 72 + Sections * 80)
        return K70_BAD_SEGMENT;
      Va = R64(Data + At + 24); Memory = R64(Data + At + 32);
      File = R64(Data + At + 40); FileBytes = R64(Data + At + 48);
      Maximum = R32(Data + At + 56); Initial = R32(Data + At + 60);
      if (Memory > (~(K70_U64)0) - Va || FileBytes > Memory ||
          File > Size || FileBytes > Size - File || (Maximum & ~7U) ||
          (Initial & ~Maximum)) return K70_BAD_SEGMENT;
      if (Memory) {
        if ((Va & 4095) || (Memory & 4095) || (FileBytes && (File & 4095)) ||
            Memory > K70_MAX_BYTES || Plan->Count == K70_MAX_SEGMENTS)
          return K70_BAD_SEGMENT;
        for (J = 0; J < Plan->Count; J++) {
          S = &Plan->Segments[J];
          if (Overlap(Va, Memory, S->Offset, S->Size) ||
              Overlap(File, FileBytes, S->FileOffset, S->FileSize))
            return K70_BAD_SEGMENT;
        }
        S = &Plan->Segments[Plan->Count++];
        S->Offset = Va; S->Size = Memory; S->FileOffset = File;
        S->FileSize = FileBytes; S->Protection = Initial;
        for (J = 0; J < 16; J++) S->Name[J] = (char)Data[At + 8 + J];
        S->Name[16] = 0;
        if (Va < Low) Low = Va;
        if (Va + Memory > High) High = Va + Memory;
      }
    } else if (Cmd == 5) {
      if (++ThreadCount != 1 || Bytes != 288 || R32(Data + At + 8) != 6 ||
          R32(Data + At + 12) != 68) return K70_BAD_ENTRY;
      Pc = R64(Data + At + 272);
    } else if (Cmd == 2 || Cmd == 0xB || Cmd == 0x1B || Cmd == 0x2A || Cmd == 0x26) {
      // Non-loading metadata present in the pinned static kernel. Nothing in
      // these records authorizes a dependency, relocation or entry override.
      K70_U32 Expected = Cmd == 0xB ? 80 : (Cmd == 2 || Cmd == 0x1B ? 24 : 16);
      if (Bytes != Expected) return K70_BAD_COMMAND;
    } else if (Cmd == 0x32) {
      K70_U32 Tools;
      if (Bytes < 24) return K70_BAD_COMMAND;
      Tools = R32(Data + At + 20);
      if (Tools > (Bytes - 24) / 8 || Bytes != 24 + Tools * 8)
        return K70_BAD_COMMAND;
    } else {
      // Includes unknown LC_REQ_DYLD, encryption and dynamic fixup commands.
      return K70_UNSUPPORTED;
    }
    At += Bytes;
  }
  if (At != End || !Plan->Count || !ThreadCount || High <= Low ||
      High - Low > K70_MAX_BYTES || (Low & 0x1FFFFFULL) != 0x4000)
    return K70_BAD_HEADER;
  if ((Pc & 3) || Pc < Low || Pc >= High) return K70_BAD_ENTRY;
  for (I = 0; I < Plan->Count; I++) {
    K70_SEGMENT *S = &Plan->Segments[I];
    if ((S->Protection & 4) && Pc >= S->Offset && Pc - S->Offset < S->FileSize)
      break;
  }
  if (I == Plan->Count) return K70_BAD_ENTRY;
  Plan->VmBase = Low; Plan->Span = High - Low; Plan->EntryOffset = Pc - Low;
  for (I = 0; I < Plan->Count; I++) Plan->Segments[I].Offset -= Low;
  return K70_OK;
}

int K70LoadMachO(const K70_U8 *Data, K70_SIZE Size, K70_U8 *Destination,
                 K70_SIZE Capacity, K70_PLAN *Plan) {
  K70_U32 I;
  K70_SIZE J, SourceAddress = (K70_SIZE)Data, DestinationAddress = (K70_SIZE)Destination;
  int Status = K70ParseMachO(Data, Size, Plan);
  if (Status) return Status;
  if (!Destination || Plan->Span > Capacity) return K70_NO_SPACE;
  if (Size > (~(K70_SIZE)0) - SourceAddress ||
      Plan->Span > (~(K70_SIZE)0) - DestinationAddress ||
      Overlap(SourceAddress, Size, DestinationAddress, Plan->Span)) return K70_NO_SPACE;
  for (J = 0; J < (K70_SIZE)Plan->Span; J++) Destination[J] = 0;
  for (I = 0; I < Plan->Count; I++) {
    K70_SEGMENT *S = &Plan->Segments[I];
    for (J = 0; J < (K70_SIZE)S->FileSize; J++)
      Destination[(K70_SIZE)S->Offset + J] = Data[(K70_SIZE)S->FileOffset + J];
  }
  return K70_OK;
}

int K70Place(const K70_PLAN *Plan, K70_U64 Base, K70_U64 Limit, K70_U64 *Entry) {
  if (!Plan || !Entry || !Plan->Span || Plan->Span > K70_MAX_BYTES ||
      Plan->EntryOffset >= Plan->Span || (Base & 0x1FFFFFULL) != 0x4000 ||
      Base >= Limit || Plan->Span > Limit - Base) return K70_NO_SPACE;
  *Entry = Base + Plan->EntryOffset;
  return K70_OK;
}

int K70RangeInReserved(K70_U64 Base, K70_U64 Size) {
  return Size && Base >= 0xA8000000ULL && Base < 0xB8000000ULL &&
         Size <= 0xB8000000ULL - Base;
}

int K70InspectPayload(const K70_U8 *Data, K70_SIZE Size,
                       const K70_U8 *KernelHash, const K70_U8 *MappedHash,
                       K70_PLAN *Plan) {
  static const K70_U8 Magic[8] = {'K','7','0','X','N','U','0','1'};
  K70_U32 I;
  int Status;
  if (!Data || !KernelHash || !MappedHash || !Plan || Size < 128 ||
      Size - 128 > K70_MAX_BYTES) return K70_BAD_PAYLOAD;
  for (I = 0; I < 8; I++) if (Data[I] != Magic[I]) return K70_BAD_PAYLOAD;
  if (R32(Data + 8) != 1 || R32(Data + 12) != 128 ||
      R64(Data + 16) != Size - 128 || R32(Data + 24) != 4096 ||
      R32(Data + 28) != 1 || R64(Data + 120) != 0) return K70_BAD_PAYLOAD;
  for (I = 0; I < 32; I++) {
    if (Data[32 + I] != KernelHash[I] || Data[64 + I] != MappedHash[I])
      return K70_BAD_PAYLOAD;
  }
  Status = K70ParseMachO(Data + 128, Size - 128, Plan);
  if (Status) return Status;
  if (R64(Data + 96) != Plan->VmBase || R64(Data + 104) != Plan->Span ||
      R64(Data + 112) != Plan->EntryOffset) return K70_BAD_PAYLOAD;
  return K70_OK;
}
