from __future__ import annotations

import base64
import gzip
import json
import re
import zlib
from pathlib import Path

import pytest

from tradingview.errors import TradingViewError
from tradingview.protocol import (
    create_session_id,
    createSessionId,
    decode_compressed,
    decode_frames,
    decodeCompressed,
    decodeFrames,
    encode_frame,
    encode_heartbeat,
    encode_packet,
    encodeFrame,
    encodeHeartbeat,
    encodePacket,
    normalise_base64,
    normaliseBase64,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
LIVE = json.loads((FIXTURES / "live-session.json").read_text(encoding="utf-8"))
COMPRESSED = json.loads((FIXTURES / "compressed-report.json").read_text(encoding="utf-8"))


class TestFraming:
    def test_encodes_packets_with_utf16_lengths(self):
        assert encodePacket("set_auth_token", ["token"]) == '~m~36~m~{"m":"set_auth_token","p":["token"]}'
        assert encodeFrame("é€") == "~m~2~m~é€"
        # Supplementary plane character (emoji) takes 2 UTF-16 code units in JS
        assert encodeFrame("😀") == "~m~2~m~😀"
        assert encodeHeartbeat(42) == "~m~5~m~~h~42"

    def test_decodes_several_frames_heartbeats_and_greeting(self):
        message = (
            encode_frame({"session_id": "abc", "protocol": "json"})
            + encode_frame("~h~7")
            + encode_packet("qsd", ["qs_1", {"n": "X", "s": "ok", "v": {"lp": 1}}])
        )
        assert decode_frames(message) == [
            {"type": "data", "data": {"session_id": "abc", "protocol": "json"}},
            {"type": "heartbeat", "id": 7},
            {"type": "packet", "packet": {"m": "qsd", "p": ["qs_1", {"n": "X", "s": "ok", "v": {"lp": 1}}]}},
        ]

    def test_keeps_payloads_containing_frame_markers_intact(self):
        tricky = {"m": "qsd", "p": ["qs_1", {"description": "weird ~m~12~m~ text", "unicode": "日本語 😀"}]}
        frames = decodeFrames(encodeFrame(tricky))
        assert len(frames) == 1
        assert frames[0] == {"type": "packet", "packet": tricky}

    def test_reports_invalid_json_instead_of_throwing(self):
        frames = decode_frames("~m~5~m~{nope")
        assert len(frames) == 1
        assert frames[0]["type"] == "invalid"

    def test_falls_back_to_splitting_malformed_input(self):
        frames = decode_frames("garbage~m~4~m~~h~1")
        assert [f["type"] for f in frames] == ["invalid", "heartbeat"]

    def test_defaults_missing_packet_parameter_list_to_empty(self):
        assert decode_frames(encode_frame({"m": "protocol_error"})) == [
            {"type": "packet", "packet": {"m": "protocol_error", "p": []}}
        ]

    def test_decodes_every_message_of_captured_live_session(self):
        frames = [frame for msg in LIVE["messages"] for frame in decode_frames(msg)]
        assert not any(f["type"] == "invalid" for f in frames)
        methods = {f["packet"]["m"] for f in frames if f["type"] == "packet"}
        expected = {
            "series_loading",
            "symbol_resolved",
            "timescale_update",
            "series_completed",
            "du",
            "study_completed",
            "qsd",
            "quote_completed",
            "symbol_error",
        }
        assert expected.issubset(methods)


class TestCompressedPayloads:
    def test_reads_deflated_zip_with_empty_entry_name(self):
        assert decodeCompressed(COMPRESSED["zipDeflated"]) == COMPRESSED["report"]

    def test_reads_stored_zip_encoded_as_unpadded_url_safe_base64(self):
        assert decode_compressed(COMPRESSED["zipStored"]) == COMPRESSED["report"]

    def test_reads_streamed_zip_that_uses_data_descriptors(self):
        assert decode_compressed(COMPRESSED["zipStreamed"]) == COMPRESSED["report"]

    def test_reads_zlib_raw_deflate_gzip_and_plain_json_payloads(self):
        raw_bytes = json.dumps(COMPRESSED["report"]).encode("utf-8")
        zlib_bytes = zlib.compress(raw_bytes)
        comp_obj = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        deflate_raw_bytes = comp_obj.compress(raw_bytes) + comp_obj.flush()
        gzip_bytes = gzip.compress(raw_bytes)

        for payload in (zlib_bytes, deflate_raw_bytes, gzip_bytes, raw_bytes):
            encoded = base64.b64encode(payload).decode("ascii")
            assert decode_compressed(encoded) == COMPRESSED["report"]

    def test_throws_parse_error_for_unknown_data(self):
        with pytest.raises(TradingViewError) as exc_info:
            decode_compressed("bm90IGpzb24")
        assert exc_info.value.code == "PARSE_ERROR"

    def test_normalises_base64(self):
        assert normaliseBase64("a-_b") == "a+/b"
        assert normalise_base64("abcde") == "abcde==="


class TestIds:
    def test_creates_prefixed_random_ids(self):
        session_id = createSessionId("cs")
        assert re.match(r"^cs_[A-Za-z0-9]{12}$", session_id)
        assert create_session_id("cs") != session_id
