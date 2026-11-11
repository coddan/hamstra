"""Writes a minimal valid (stored, uncompressed) RAR 4 archive so tests need no RAR tool."""
import struct
import zlib
from pathlib import Path


def write_rar(path: Path, name: str, data: bytes) -> None:
    def block(btype: int, flags: int, body: bytes) -> bytes:
        size = 7 + len(body)
        head = struct.pack("<BHH", btype, flags, size) + body
        return struct.pack("<H", zlib.crc32(head) & 0xFFFF) + head

    nm = name.encode()
    file_body = struct.pack("<IIBIIBBHI", len(data), len(data), 3, zlib.crc32(data) & 0xFFFFFFFF, 0x5A000000,
                            29, 0x30, len(nm), 0o100644) + nm
    path.write_bytes(
        b"Rar!\x1a\x07\x00" + block(0x73, 0, b"\x00\x00\x00\x00\x00\x00") + block(0x74, 0x8000, file_body) + data
        + bytes.fromhex("c43d7b00400700")
    )
