"""Find the actual probe application FFS file and its PE32 section in FVMAIN."""
import struct
import uuid

PROBE_GUID = uuid.UUID("4E746B99-462F-4C10-8A77-C3F83E5D4F72").bytes_le


def probe_pe(blob):
    if len(blob) < 56 or blob[40:44] != b"_FVH":
        raise ValueError("Not an EFI firmware volume")
    end = struct.unpack_from("<Q", blob, 32)[0]
    if end > len(blob):
        raise ValueError("Truncated firmware volume")
    start = struct.unpack_from("<H", blob, 48)[0]
    ext = struct.unpack_from("<H", blob, 52)[0]
    if ext:
        if ext + 20 > end:
            raise ValueError("Truncated extended FV header")
        start = max(start, ext + struct.unpack_from("<I", blob, ext + 16)[0])
    offset = (start + 7) & ~7
    while offset + 24 <= end:
        if blob[offset:offset+24] == b"\xff" * 24:
            break
        size = int.from_bytes(blob[offset+20:offset+23], "little")
        header = 24
        if size == 0xffffff:
            if offset + 32 > end:
                raise ValueError("Truncated extended FFS header")
            size = struct.unpack_from("<Q", blob, offset+24)[0]
            header = 32
        if size < header or offset + size > end:
            raise ValueError("Invalid FFS file size")
        if blob[offset:offset+16] == PROBE_GUID and blob[offset+18] == 9:
            section = offset + header
            while section + 4 <= offset + size:
                count = int.from_bytes(blob[section:section+3], "little")
                section_header = 4
                if count == 0xffffff:
                    if section + 8 > offset + size:
                        raise ValueError("Truncated extended section")
                    count = struct.unpack_from("<I", blob, section+4)[0]
                    section_header = 8
                if count < section_header or section + count > offset + size:
                    raise ValueError("Invalid FFS section size")
                if blob[section+3] == 0x10:
                    return blob[section+section_header:section+count]
                section += (count + 3) & ~3
            raise ValueError("Probe application has no direct PE32 section")
        offset = (offset + size + 7) & ~7
    raise ValueError("Probe application GUID is absent from firmware volume")
