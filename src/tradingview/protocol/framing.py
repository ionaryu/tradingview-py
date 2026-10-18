from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from .._types import AttrDict

HEADER = "~m~"
HEARTBEAT = "~h~"
_FRAME_SPLIT_RE = re.compile(r"~m~\d+~m~")

ServerPacket = dict[str, Any]
ServerHello = dict[str, Any]
Frame = dict[str, Any]


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _decode_payload(raw: str) -> Frame:
    if raw.startswith(HEARTBEAT):
        suffix = raw[len(HEARTBEAT) :].strip()
        if suffix and (suffix.isdigit() or (suffix.startswith("-") and suffix[1:].isdigit())):
            return AttrDict({"type": "heartbeat", "id": int(suffix)})
        try:
            num = float(raw[len(HEARTBEAT) :])
            if num == int(num):
                return AttrDict({"type": "heartbeat", "id": int(num)})
        except ValueError:
            pass
        return AttrDict({"type": "invalid", "raw": raw, "error": ValueError("Invalid heartbeat")})

    try:
        data = json.loads(raw)
    except Exception as error:
        return AttrDict({"type": "invalid", "raw": raw, "error": error})

    if isinstance(data, dict) and isinstance(data.get("m"), str):
        p = data.get("p")
        packet = {**data, "p": p if isinstance(p, list) else []}
        return AttrDict({"type": "packet", "packet": packet})

    return AttrDict({"type": "data", "data": data})


def _split_frames(input_str: str) -> list[str]:
    return [part for part in _FRAME_SPLIT_RE.split(input_str) if len(part) > 0]


def decode_frames(input_str: str) -> list[Frame]:
    """Decodes a raw websocket message into frames using UTF-16 code unit lengths."""
    payloads: list[str] = []
    # Check if string contains any supplementary plane characters (ord > 0xFFFF)
    raw_u16 = input_str.encode("utf-16-le")
    total_u16 = len(raw_u16) // 2

    if total_u16 == len(input_str):
        # Fast path: all BMP characters, Python index == UTF-16 index
        position = 0
        n = len(input_str)
        while position < n:
            if not input_str.startswith(HEADER, position):
                payloads.extend(_split_frames(input_str[position:]))
                break
            length_start = position + len(HEADER)
            length_end = input_str.find(HEADER, length_start)
            if length_end < 0:
                payloads.extend(_split_frames(input_str[position:]))
                break
            length_str = input_str[length_start:length_end]
            if not length_str.isdigit():
                payloads.extend(_split_frames(input_str[position:]))
                break
            length = int(length_str)
            start = length_end + len(HEADER)
            payloads.append(input_str[start : start + length])
            position = start + length
    else:
        # Exact UTF-16 code unit indexing
        header_u16 = HEADER.encode("utf-16-le")
        header_len_u16 = len(HEADER)
        pos_u16 = 0
        while pos_u16 < total_u16:
            byte_pos = pos_u16 * 2
            if raw_u16[byte_pos : byte_pos + len(header_u16)] != header_u16:
                tail = raw_u16[byte_pos:].decode("utf-16-le", errors="replace")
                payloads.extend(_split_frames(tail))
                break
            length_start_u16 = pos_u16 + header_len_u16
            # Find next HEADER on even byte boundary
            search_from = length_start_u16 * 2
            found_byte = -1
            idx = raw_u16.find(header_u16, search_from)
            while idx != -1:
                if idx % 2 == 0:
                    found_byte = idx
                    break
                idx = raw_u16.find(header_u16, idx + 1)
            if found_byte < 0:
                tail = raw_u16[byte_pos:].decode("utf-16-le", errors="replace")
                payloads.extend(_split_frames(tail))
                break
            length_str = raw_u16[search_from:found_byte].decode("utf-16-le", errors="replace")
            if not length_str.isdigit():
                tail = raw_u16[byte_pos:].decode("utf-16-le", errors="replace")
                payloads.extend(_split_frames(tail))
                break
            length = int(length_str)
            start_u16 = (found_byte // 2) + header_len_u16
            end_u16 = start_u16 + length
            payload_bytes = raw_u16[start_u16 * 2 : end_u16 * 2]
            payloads.append(payload_bytes.decode("utf-16-le", errors="replace"))
            pos_u16 = end_u16

    return [_decode_payload(p) for p in payloads]


def encode_frame(payload: str | dict[str, Any] | list[Any]) -> str:
    """Encodes one frame. Objects are JSON-encoded without extra whitespace."""
    body = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    length = _utf16_len(body)
    return f"{HEADER}{length}{HEADER}{body}"


def encode_packet(method: str, params: Sequence[Any] = ()) -> str:
    """Encodes a client packet (`{ m: method, p: params }`)."""
    return encode_frame({"m": method, "p": list(params)})


def encode_heartbeat(heartbeat_id: int) -> str:
    """Encodes the reply to a server heartbeat."""
    return encode_frame(f"{HEARTBEAT}{heartbeat_id}")


decodeFrames = decode_frames
encodeFrame = encode_frame
encodePacket = encode_packet
encodeHeartbeat = encode_heartbeat
