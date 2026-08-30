"""Tests for FastAPI endpoints."""

import json
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app.api.server import app

client = TestClient(app)
AUTH = {"X-API-Key": "test-api-key-for-ci"}


class TestHealth:
    def test_health(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "engines" in data


class TestAnalyze:
    def test_single_value(self):
        resp = client.post("/api/analyze", json={
            "input_type": "auto",
            "value": "$1499.00",
        }, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert "input_classification" in data

    def test_dataset(self):
        resp = client.post("/api/analyze", json={
            "input_type": "manual_dataset",
            "values": [100, 200, 300, 400, 500] * 20,
        }, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert "statistical_analysis" in data

    def test_card_number(self):
        resp = client.post("/api/analyze", json={
            "input_type": "auto",
            "value": "4532015112830366",
        }, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        checks = data.get("checks", [])
        check_names = [c["check"] for c in checks]
        assert "luhn_checksum" in check_names

    def test_empty_dataset_rejected(self):
        resp = client.post("/api/analyze", json={
            "input_type": "manual_dataset",
            "values": [],
        }, headers=AUTH)
        assert resp.status_code == 400

    def test_auto_no_input(self):
        resp = client.post("/api/analyze", json={
            "input_type": "auto",
        }, headers=AUTH)
        assert resp.status_code == 400

    def test_invalid_input_type(self):
        resp = client.post("/api/analyze", json={
            "input_type": "bogus",
        }, headers=AUTH)
        assert resp.status_code == 400


class TestUpload:
    def test_invalid_file_type(self):
        resp = client.post(
            "/api/analyze/upload",
            files={"file": ("test.exe", b"binary", "application/octet-stream")},
            headers=AUTH,
        )
        assert resp.status_code == 400

    def test_csv_upload(self):
        csv_content = b"id,amount,date\n1,100,2026-01-01\n2,200,2026-01-02\n"
        resp = client.post(
            "/api/analyze/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
            headers=AUTH,
        )
        assert resp.status_code == 200


class TestClassifyImage:
    """The /api/classify/image endpoint used to narrate the processing screen."""

    @staticmethod
    def _png(tmp_path, name="doc.png"):
        from PIL import Image

        path = tmp_path / name
        Image.new("RGB", (320, 200), (240, 240, 240)).save(path)
        return path

    def test_returns_null_guess_when_vision_unconfigured(self, tmp_path):
        """No API key must yield a well-formed empty guess, not an error —
        the client falls back to generic progress copy."""
        path = self._png(tmp_path)
        with open(path, "rb") as f:
            resp = client.post(
                "/api/classify/image",
                files={"file": ("doc.png", f, "image/png")},
                headers=AUTH,
            )

        assert resp.status_code == 200
        assert resp.json() == {"guess": None}

    def test_rejects_non_image_extension(self, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_text("plain text")
        with open(path, "rb") as f:
            resp = client.post(
                "/api/classify/image",
                files={"file": ("notes.txt", f, "text/plain")},
                headers=AUTH,
            )

        assert resp.status_code == 200
        assert resp.json() == {"guess": None}

    def test_surfaces_a_real_guess(self, tmp_path, monkeypatch):
        """A configured vision model's verdict must reach the client verbatim."""
        import app.engines.classifier as classifier_module

        monkeypatch.setattr(
            classifier_module,
            "classify_image_document",
            lambda _p: classifier_module.VisionClassification(
                "credit_card", "card_number", 0.93, "embossed digits and network mark"
            ),
        )

        path = self._png(tmp_path)
        with open(path, "rb") as f:
            resp = client.post(
                "/api/classify/image",
                files={"file": ("doc.png", f, "image/png")},
                headers=AUTH,
            )

        assert resp.status_code == 200
        guess = resp.json()["guess"]
        assert guess["document_type"] == "credit_card"
        assert guess["value_type"] == "card_number"
        assert guess["confidence"] == 0.93


class TestVisionGuessReuse:
    """The client hands back the verdict it already fetched from
    /api/classify/image so analysis does not pay for the same classification
    twice — but that verdict arrives over the wire and is not trusted."""

    @staticmethod
    def _png(tmp_path):
        from PIL import Image

        path = tmp_path / "doc.png"
        Image.new("RGB", (320, 200), (240, 240, 240)).save(path)
        return path

    @staticmethod
    def _guess(**overrides):
        payload = {
            "document_type": "credit_card",
            "value_type": "card_number",
            "confidence": 0.95,
            "reason": "visa mark",
        }
        payload.update(overrides)
        return json.dumps(payload)

    def test_supplied_guess_prevents_a_second_vision_call(self, tmp_path):
        with mock.patch("app.orchestrator._classify_image_with_vision") as spy:
            with open(self._png(tmp_path), "rb") as f:
                resp = client.post(
                    "/api/analyze/upload",
                    files={"file": ("doc.png", f, "image/png")},
                    data={"vision_guess": self._guess()},
                    headers=AUTH,
                )

        assert resp.status_code == 200
        assert not spy.called, "vision must not be re-run when the caller supplied a verdict"
        assert resp.json()["extracted_data"]["vision_document_type"] == "credit_card"

    def test_missing_guess_still_classifies_server_side(self, tmp_path):
        with mock.patch("app.orchestrator._classify_image_with_vision", return_value=None) as spy:
            with open(self._png(tmp_path), "rb") as f:
                resp = client.post(
                    "/api/analyze/upload",
                    files={"file": ("doc.png", f, "image/png")},
                    headers=AUTH,
                )

        assert resp.status_code == 200
        assert spy.called, "without a supplied verdict the server must classify the image itself"

    @pytest.mark.parametrize("raw", [
        '{"document_type":"forged_note","value_type":"card_number","confidence":0.9}',
        '{"document_type":"credit_card","value_type":"bank_pin","confidence":0.9}',
        '{"document_type":"credit_card","value_type":"card_number","confidence":"high"}',
        "not json at all",
        "[1,2,3]",
        "",
    ])
    def test_untrusted_input_is_rejected(self, raw):
        """A tampered verdict must be discarded, not honoured — otherwise a
        client could dictate the document type the checks run against."""
        from app.api.server import _parse_vision_guess

        assert _parse_vision_guess(raw) is None

    def test_confidence_is_clamped_not_trusted(self):
        from app.api.server import _parse_vision_guess

        parsed = _parse_vision_guess(self._guess(confidence=99))
        assert parsed is not None
        assert parsed.confidence == 0.95
