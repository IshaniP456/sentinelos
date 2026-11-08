"""Bounded inline image input and explicit scripted fixture. Author: Tishneet."""
import base64
import binascii
import hashlib
from pathlib import Path
import struct

MAX_IMAGE_BYTES = 128 * 1024  # Inline image + plan must fit the DynamoDB document.
DEMO_MODE = "image_injection_v1"
DEMO_INSTRUCTION = "Move 11 packages from Zone A to Zone C."


def demo_image():
    return Path(__file__).with_name("assets").joinpath("image-injection-v1.png").read_bytes()


def _dimensions(data, mime_type):
    if mime_type == "image/png":
        if (len(data) < 45 or not data.startswith(b"\x89PNG\r\n\x1a\n")
                or data[12:16] != b"IHDR" or data[-8:-4] != b"IEND"):
            raise ValueError("Provide a PNG image with its complete header and end marker.")
        return struct.unpack(">II", data[16:24])
    if not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9"):
        raise ValueError("Provide a complete JPEG image.")
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 255:
            break
        while offset < len(data) and data[offset] == 255:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            break
        size = int.from_bytes(data[offset:offset + 2], "big")
        if size < 2 or offset + size > len(data):
            break
        if marker in (0xC0, 0xC2) and size >= 8:
            height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
            return width, height
        if marker == 0xDA:
            break
        offset += size
    raise ValueError("JPEG must contain a supported baseline or progressive frame.")


def validate_image(image_b64, mime_type):
    """Check transport/format bounds; Bedrock still decodes image contents."""
    if mime_type not in ("image/png", "image/jpeg"):
        raise ValueError("mime_type must be image/png or image/jpeg.")
    if (not isinstance(image_b64, str) or not image_b64
            or len(image_b64) > 4 * ((MAX_IMAGE_BYTES + 2) // 3)):
        raise ValueError("Provide a base64 image of at most 128 KiB decoded size.")
    try:
        data = base64.b64decode(image_b64, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("image_b64 must be raw base64 without a data-URL prefix.") from None
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Decoded image exceeds the 128 KiB limit.")
    width, height = _dimensions(data, mime_type)
    if not 0 < width <= 4096 or not 0 < height <= 4096 or width * height > 4_000_000:
        raise ValueError("Image dimensions exceed the supported preview bounds.")
    return {"image_b64": image_b64, "mime_type": mime_type,
            "format": "png" if mime_type == "image/png" else "jpeg",
            "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
            "width": width, "height": height}
