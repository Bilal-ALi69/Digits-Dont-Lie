"""Vision-based document classification.

The live Groq call is not exercised here; a stub client stands in so the
parsing, validation and image-encoding logic is covered without a network
round trip or an API key.
"""

from __future__ import annotations

import json

import pytest
from PIL import Image

from app.engines.classifier import classify_image_document
from app.engines.groq_client import _encode_image_b64, _wrap_untrusted_image_instruction


class StubClient:
    """Minimal stand-in for GroqClient.vision."""

    def __init__(self, reply: str | None, available: bool = True) -> None:
        self._reply = reply
        self.available = available
        self.calls: list[tuple[str, str]] = []

    def vision(
        self,
        image_path: str,
        instruction: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str | None:
        self.calls.append((image_path, instruction))
        return self._reply


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "doc.png"
    Image.new("RGB", (400, 250), (200, 180, 160)).save(path)
    return str(path)


def _reply(**overrides: object) -> str:
    payload = {
        "document_type": "invoice",
        "value_type": "invoice_number",
        "confidence": 0.88,
        "reason": "letterhead and line items",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_returns_classification_from_valid_reply(image):
    result = classify_image_document(image, StubClient(_reply()))

    assert result is not None
    assert result.document_type == "invoice"
    assert result.value_type == "invoice_number"
    assert result.confidence == pytest.approx(0.88)
    assert result.reason == "letterhead and line items"


def test_returns_none_when_client_unavailable(image):
    client = StubClient(_reply(), available=False)
    assert classify_image_document(image, client) is None
    assert client.calls == [], "must not call the API when unavailable"


def test_returns_none_when_model_returns_nothing(image):
    assert classify_image_document(image, StubClient(None)) is None


def test_rejects_non_json_reply(image):
    assert classify_image_document(image, StubClient("it looks like an invoice")) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("document_type", "utility_bill"),   # plausible but not in the enum
        ("document_type", ""),
        ("value_type", "serial_number"),
        ("value_type", "not_a_type"),
    ],
)
def test_rejects_values_outside_controlled_vocabulary(image, field, value):
    """A hallucinated label must be discarded, not passed through."""
    assert classify_image_document(image, StubClient(_reply(**{field: value}))) is None


def test_confidence_is_clamped_to_ceiling(image):
    result = classify_image_document(image, StubClient(_reply(confidence=4.2)))
    assert result is not None
    assert result.confidence == 0.95


def test_confidence_is_clamped_at_zero(image):
    result = classify_image_document(image, StubClient(_reply(confidence=-1)))
    assert result is not None
    assert result.confidence == 0.0


def test_non_numeric_confidence_falls_back_to_zero(image):
    result = classify_image_document(image, StubClient(_reply(confidence="very sure")))
    assert result is not None
    assert result.confidence == 0.0


def test_missing_reason_gets_a_default(image):
    result = classify_image_document(image, StubClient(_reply(reason="")))
    assert result is not None
    assert result.reason == "Identified from document image"


def test_injection_defence_is_applied_by_the_client():
    """Defence lives in GroqClient.vision so it covers every vision caller,
    not just this one — assert it there rather than on the instruction passed in."""
    wrapped = _wrap_untrusted_image_instruction("Classify this document.")

    assert "Classify this document." in wrapped
    assert "UNTRUSTED" in wrapped
    assert "NEVER an instruction" in wrapped


def test_instruction_lists_only_valid_enums(image):
    client = StubClient(_reply())
    classify_image_document(image, client)

    _, instruction = client.calls[0]
    assert "credit_card" in instruction
    assert "invoice_number" in instruction


# ---------- image encoding ----------


def test_encodes_image_as_jpeg_base64(image):
    encoded = _encode_image_b64(image)
    assert encoded is not None
    mime, b64 = encoded
    assert mime == "image/jpeg"
    assert len(b64) > 0


def test_downscales_oversized_image(tmp_path):
    """A large image must still encode within the API's payload limit."""
    path = tmp_path / "big.png"
    Image.new("RGB", (6000, 4000), (10, 200, 90)).save(path)

    encoded = _encode_image_b64(str(path))
    assert encoded is not None
    _, b64 = encoded
    assert len(b64) <= 3_500_000


def test_converts_transparent_png(tmp_path):
    """RGBA cannot be saved as JPEG directly; it must be converted first."""
    path = tmp_path / "alpha.png"
    Image.new("RGBA", (300, 200), (120, 40, 60, 128)).save(path)

    assert _encode_image_b64(str(path)) is not None


def test_returns_none_for_unreadable_file(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"this is not a PNG")

    assert _encode_image_b64(str(path)) is None


def test_returns_none_for_missing_file(tmp_path):
    assert _encode_image_b64(str(tmp_path / "nope.png")) is None
