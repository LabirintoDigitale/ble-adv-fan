"""Kaiyu LEGO compatible light controller (12 LED outputs) protocol.

Two layers:
- the Mould King BLE advertising whitening (port of MouldKingCrypt from J0EK3R/mkconnect-python, MIT License),
- the Kaiyu app payload: 14 bytes with the state of the 12 outputs, each byte offset by a value from
  3 tables selected by a random seed, and a checksum.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import randint

LINES_NB = 12
LINE_ON = 2
LINE_OFF = 1
MODE_ALL = bytes([0x55, 0xAA])
MODE_LINES = bytes([0x00, 0x00])
DEFAULT_COMPANY = bytes([0x00, 0xC2])

PAYLOAD_LEN = 14
TELEGRAM_LEN = 24
_ADDRESS = bytes([0xC1, 0xC2, 0xC3, 0xC4, 0xC5])

_TAB_37 = (141, 210, 87, 161, 61, 167, 102, 176, 117, 49, 17, 72, 150, 119, 248, 227, 70, 233, 171, 208, 158, 83, 51, 216, 186, 152, 8, 36, 203, 59, 252, 113, 163, 244, 85, 104)  # fmt: skip
_TAB_38 = (214, 197, 68, 32, 89, 222, 225, 143, 27, 165, 175, 66, 123, 78, 205, 96, 235, 98, 34, 144, 44, 239, 240, 199, 141, 210, 87, 161, 61, 167, 102, 176, 117, 49, 17, 72)  # fmt: skip
_TAB_39 = (31, 55, 74, 95, 133, 246, 156, 154, 193, 214, 197, 68, 32, 89, 222, 225, 143, 27, 165, 175, 66, 123, 78, 205, 96, 235, 98, 34, 144, 44, 239, 240, 199, 141, 210, 87)  # fmt: skip


def _reverse_8(value: int) -> int:
    return int(f"{value:08b}"[::-1], 2)


def _reverse_16(value: int) -> int:
    return int(f"{value:016b}"[::-1], 2)


def _whitening_bits(seed: int, nb_bits: int) -> list[int]:
    """Bits of the 7 bits LFSR whitening sequence, as used by the Mould King app."""
    lfsr = [1] + [(seed >> (6 - i)) & 1 for i in range(1, 7)]
    bits = []
    for _ in range(nb_bits):
        r1 = lfsr[3] ^ lfsr[6]
        lfsr[3], lfsr[2], lfsr[1], lfsr[0] = lfsr[2], lfsr[1], lfsr[0], lfsr[6]
        lfsr[6], lfsr[5], lfsr[4] = lfsr[5], lfsr[4], r1
        bits.append(lfsr[0])
    return bits


def _whiten(buffer: bytearray, seed: int) -> None:
    bits = _whitening_bits(seed, 8 * len(buffer))
    for index, value in enumerate(buffer):
        buffer[index] = value ^ sum(bits[8 * index + bit] << bit for bit in range(8))


def _crc16(data: bytes) -> int:
    result = 0xFFFF
    for value in [*reversed(_ADDRESS), *(_reverse_8(x) for x in data)]:
        result ^= value << 8
        for _ in range(8):
            result = ((result << 1) ^ 0x1021) if result & 0x8000 else (result << 1)
            result &= 0xFFFF
    return _reverse_16(result) ^ 0xFFFF


def mk_crypt(data: bytes) -> bytes:
    """Mould King whitening of the data into a 24 bytes telegram."""
    target = bytearray(len(_ADDRESS) + len(data) + 20)
    target[15:18] = bytes([0x71, 0x0F, 0x55])
    target[18:23] = bytes(reversed(_ADDRESS))
    target[23 : 23 + len(data)] = data
    for index in range(15, 23):
        target[index] = _reverse_8(target[index])
    crc = _crc16(data)
    target[23 + len(data)] = crc & 0xFF
    target[24 + len(data)] = crc >> 8
    tail = target[18:]
    _whiten(tail, 63)
    target[18:] = tail
    _whiten(target, 37)
    telegram = bytearray(i + 1 for i in range(TELEGRAM_LEN))
    res_len = len(_ADDRESS) + len(data) + 5
    telegram[:res_len] = target[15 : 15 + res_len]
    return bytes(telegram)


_ZERO_TELEGRAM = mk_crypt(bytes(PAYLOAD_LEN))


def mk_decrypt(telegram: bytes) -> bytes | None:
    """Recover the 14 bytes payload of a Mould King telegram, None if not one (header or CRC invalid)."""
    if len(telegram) != TELEGRAM_LEN or telegram[:8] != _ZERO_TELEGRAM[:8]:
        return None
    data = bytes(telegram[8 + i] ^ _ZERO_TELEGRAM[8 + i] for i in range(PAYLOAD_LEN))
    return data if mk_crypt(data) == bytes(telegram) else None


@dataclass
class KaiyuCommand:
    """Decoded Kaiyu command."""

    mode: bytes
    device_id: bytes
    lines: list[bool | None]  # None: unknown output value (not ON / OFF)


def _offsets(seed: int) -> tuple[int, ...]:
    a, b, c = seed & 31, (seed >> 3) & 31, (seed >> 1) & 31
    return (_TAB_37[a], _TAB_37[a + 1], _TAB_38[b], _TAB_39[b], _TAB_39[b + 1], _TAB_38[c], _TAB_38[c + 1], _TAB_38[c + 3] - 1)


def kaiyu_encode(mode: bytes, device_id: bytes, lines: list[bool], seed: int | None = None) -> bytes:
    """Encode the state of the 12 outputs into the 14 bytes payload."""
    seed = randint(1, 256) if seed is None else seed
    nibbles = [LINE_ON if on else LINE_OFF for on in lines]
    values = [(nibbles[2 * i] << 4) | nibbles[2 * i + 1] for i in range(LINES_NB // 2)] + [0]
    offs = _offsets(seed)
    payload = bytearray(PAYLOAD_LEN)
    payload[0:2] = mode
    payload[2:4] = device_id
    for pos, value, off in zip((4, 5, 6, 7, 8, 11, 12), values, offs, strict=False):
        payload[pos] = (value + off) & 0xFF
    payload[10] = seed & 0xFF
    payload[13] = offs[7] & 0xFF
    payload[9] = (sum(payload) + 0x66) & 0xFF
    return bytes(payload)


def kaiyu_decode(payload: bytes) -> KaiyuCommand | None:
    """Decode a 14 bytes payload, None if the checksum is invalid."""
    if len(payload) != PAYLOAD_LEN:
        return None
    offs = _offsets(payload[10])
    if payload[13] != offs[7] & 0xFF or payload[9] != (sum(payload) - payload[9] + 0x66) & 0xFF:
        return None
    values = [(payload[pos] - off) & 0xFF for pos, off in zip((4, 5, 6, 7, 8), offs, strict=False)]
    values += [(payload[11] - offs[5]) & 0xFF]
    nibbles = [n for value in values for n in (value >> 4, value & 0x0F)]
    lines = [True if n == LINE_ON else False if n == LINE_OFF else None for n in nibbles]
    return KaiyuCommand(bytes(payload[0:2]), bytes(payload[2:4]), lines)


def kaiyu_build_adv(company: bytes, payload: bytes) -> bytes:
    """Build the full raw advertisement for the payload."""
    telegram = mk_crypt(payload)
    return bytes([0x02, 0x01, 0x02, len(telegram) + 3, 0xFF, *company, *telegram])


def kaiyu_parse_adv(manufacturer_data: bytes) -> tuple[bytes, KaiyuCommand] | None:
    """Parse the manufacturer data (company id + telegram) of a received advertisement."""
    if (payload := mk_decrypt(manufacturer_data[2:])) is None:
        return None
    if (cmd := kaiyu_decode(payload)) is None:
        return None
    return bytes(manufacturer_data[:2]), cmd
