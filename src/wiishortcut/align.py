"""Explicit alignment helpers for WAD sections.

WAD sections are padded to 64 bytes. These functions are the ones this
project calls when it reasons about alignment itself. libWiiPy pads its own
serialized sections with the same modulus.
"""


def align(value: int, boundary: int = 0x40) -> int:
    """Return the next multiple of `boundary` that is >= `value`."""
    if boundary <= 0:
        raise ValueError("alignment boundary must be positive")
    if value < 0:
        raise ValueError("alignment value must be non-negative")
    remainder = value % boundary
    if remainder == 0:
        return value
    return value + (boundary - remainder)


def pad(data: bytes, boundary: int = 0x40) -> bytes:
    """Append zero bytes until `len(data)` is a multiple of `boundary`."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("pad() expects bytes")
    target = align(len(data), boundary)
    if target == len(data):
        return bytes(data)
    return bytes(data) + (b"\x00" * (target - len(data)))
