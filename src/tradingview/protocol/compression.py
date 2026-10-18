from __future__ import annotations

import base64
import gzip
import json
import re
import struct
import zlib
from typing import Any

from ..errors import TradingViewError

LOCAL_FILE_HEADER = 0x04034B50
CENTRAL_DIRECTORY_HEADER = 0x02014B50
END_OF_CENTRAL_DIRECTORY = 0x06054B50


def normalise_base64(data: str) -> str:
    """Normalises URL-safe and unpadded base64."""
    normalised = re.sub(r"\s", "", data.replace("-", "+").replace("_", "/"))
    pad = (4 - (len(normalised) % 4)) % 4
    return normalised + ("=" * pad)


normaliseBase64 = normalise_base64


def _inflate_entry(method: int, data: bytes) -> bytes:
    if method == 0:
        return data
    if method == 8:
        return zlib.decompress(data, -zlib.MAX_WBITS)
    raise ValueError(f"Unsupported ZIP compression method {method}")


def read_first_zip_entry(archive: bytes | bytearray | memoryview) -> bytes:
    """Reads the first file of a ZIP archive (stored or deflated)."""
    buf = bytes(archive)
    n = len(buf)
    min_eocd = max(0, n - 0xFFFF - 22)
    for eocd in range(n - 22, min_eocd - 1, -1):
        if struct.unpack_from("<I", buf, eocd)[0] != END_OF_CENTRAL_DIRECTORY:
            continue
        entries = struct.unpack_from("<H", buf, eocd + 10)[0]
        cursor = struct.unpack_from("<I", buf, eocd + 16)[0]
        for _ in range(entries):
            if cursor + 46 > n or struct.unpack_from("<I", buf, cursor)[0] != CENTRAL_DIRECTORY_HEADER:
                break
            method = struct.unpack_from("<H", buf, cursor + 10)[0]
            compressed_size = struct.unpack_from("<I", buf, cursor + 20)[0]
            name_length = struct.unpack_from("<H", buf, cursor + 28)[0]
            extra_length = struct.unpack_from("<H", buf, cursor + 30)[0]
            comment_length = struct.unpack_from("<H", buf, cursor + 32)[0]
            local_offset = struct.unpack_from("<I", buf, cursor + 42)[0]
            name = buf[cursor + 46 : cursor + 46 + name_length].decode("utf-8", errors="replace")
            cursor += 46 + name_length + extra_length + comment_length
            if name.endswith("/"):
                continue
            local_name_length = struct.unpack_from("<H", buf, local_offset + 26)[0]
            local_extra_length = struct.unpack_from("<H", buf, local_offset + 28)[0]
            start = local_offset + 30 + local_name_length + local_extra_length
            return _inflate_entry(method, buf[start : start + compressed_size])
        break

    if n >= 30 and struct.unpack_from("<I", buf, 0)[0] == LOCAL_FILE_HEADER:
        method = struct.unpack_from("<H", buf, 8)[0]
        compressed_size = struct.unpack_from("<I", buf, 18)[0]
        local_name_length = struct.unpack_from("<H", buf, 26)[0]
        local_extra_length = struct.unpack_from("<H", buf, 28)[0]
        start = 30 + local_name_length + local_extra_length
        end = start + compressed_size if compressed_size > 0 else n
        return _inflate_entry(method, buf[start:end])

    raise ValueError("Not a ZIP archive")


readFirstZipEntry = read_first_zip_entry


def decode_compressed(data: str) -> Any:
    """Decodes a TradingView compressed payload into JSON."""
    try:
        buf = base64.b64decode(normalise_base64(data))
    except Exception as exc:
        raise TradingViewError("PARSE_ERROR", "Unable to decode compressed payload", {"cause": exc}) from exc

    readers = (
        lambda: read_first_zip_entry(buf),
        lambda: buf,
        lambda: zlib.decompress(buf),
        lambda: zlib.decompress(buf, -zlib.MAX_WBITS),
        lambda: gzip.decompress(buf),
    )

    last_error: Exception | None = None
    for reader in readers:
        try:
            raw = reader()
            return json.loads(raw.decode("utf-8"))
        except Exception as err:
            last_error = err

    raise TradingViewError("PARSE_ERROR", "Unable to decode compressed payload", {"cause": last_error})


decodeCompressed = decode_compressed
