"""API endpoint tests: upload, polling, exports, failures and caching."""

from __future__ import annotations

import json
from typing import Any

from conftest import FakeLLMClient, build_blank_pdf
from fastapi.testclient import TestClient

from mindmap_generator.api.main import create_app
from mindmap_generator.config import Settings

BASE_SETTINGS: dict[str, Any] = {
    "llm_provider": "mock",
    "max_pages": 50,
    "cache_enabled": True,
}


def make_client(llm=None, **overrides):
    settings = Settings(**{**BASE_SETTINGS, **overrides})
    app = create_app(settings, llm=llm or FakeLLMClient())
    return TestClient(app)


def upload(client: TestClient, data: bytes, *, filename="sample.pdf", content_type="application/pdf", form=None):
    return client.post(
        "/mindmaps",
        files={"file": (filename, data, content_type)},
        data=form or {},
    )


def test_health_and_docs() -> None:
    with make_client() as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["llm_provider"] == "fake"
        assert body["llm_model"] == "fake-model-v1"
        assert client.get("/docs").status_code == 200
        openapi = client.get("/openapi.json").json()
        assert "/mindmaps" in openapi["paths"]


def test_upload_status_and_exports(sample_pdf_bytes: bytes) -> None:
    fake = FakeLLMClient()
    with make_client(fake) as client:
        response = upload(client, sample_pdf_bytes)
        assert response.status_code == 202
        created = response.json()
        assert created["status"] == "pending"
        assert created["status_url"] == f"/mindmaps/{created['job_id']}"

        status_response = client.get(created["status_url"])
        assert status_response.status_code == 200
        job = status_response.json()
        assert job["status"] == "completed"
        assert job["stage"] == "finalize"
        assert job["progress"] == 1.0
        assert job["error"] is None
        result = job["result"]
        assert result["mindmap"]["id"] == "root"
        assert result["mindmap"]["label"] == "Photosynthesis"
        assert result["document"]["pages"] == 3
        assert result["meta"]["node_count"] >= 5
        assert len(fake.calls) == 1

        json_export = client.get(f"/mindmaps/{created['job_id']}/export?format=json")
        assert json_export.status_code == 200
        assert json_export.headers["content-type"].startswith("application/json")
        assert "attachment" in json_export.headers["content-disposition"]
        assert json.loads(json_export.text) == result

        markdown = client.get(f"/mindmaps/{created['job_id']}/export?format=markdown")
        assert markdown.status_code == 200
        assert markdown.headers["content-type"].startswith("text/markdown")
        assert "# Photosynthesis" in markdown.text
        assert "_Source pages:" in markdown.text
        assert "## " in markdown.text


def test_generation_options_are_applied(sample_pdf_bytes: bytes) -> None:
    fake = FakeLLMClient()
    with make_client(fake) as client:
        response = upload(
            client,
            sample_pdf_bytes,
            form={"max_depth": "2", "max_branches": "3", "language": "ru"},
        )
        assert response.status_code == 202
        job = client.get(f"/mindmaps/{response.json()['job_id']}").json()
        assert job["status"] == "completed"
        result = job["result"]
        assert result["meta"]["depth"] <= 2
        assert len(result["mindmap"]["children"]) <= 3
        assert result["meta"]["output_language"] == "ru"
        assert "OUTPUT LANGUAGE: Russian" in fake.calls[0]["user"]


def test_result_cache_by_file_hash(sample_pdf_bytes: bytes) -> None:
    fake = FakeLLMClient()
    with make_client(fake) as client:
        first = upload(client, sample_pdf_bytes)
        assert first.status_code == 202
        first_job = client.get(f"/mindmaps/{first.json()['job_id']}").json()
        assert first_job["cache_hit"] is False
        assert len(fake.calls) == 1

        second = upload(client, sample_pdf_bytes)
        assert second.status_code == 202
        second_job = client.get(f"/mindmaps/{second.json()['job_id']}").json()
        assert second_job["status"] == "completed"
        assert second_job["cache_hit"] is True
        assert second_job["result"]["meta"]["cache_hit"] is True
        assert len(fake.calls) == 1  # no additional LLM calls


def test_rejects_oversized_upload(sample_pdf_bytes: bytes) -> None:
    with make_client(max_upload_mb=1) as client:
        payload = b"%PDF-1.7\n" + b"0" * (1024 * 1024 + 16)
        response = upload(client, payload)
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "file_too_large"


def test_rejects_wrong_extension_and_mime(sample_pdf_bytes: bytes) -> None:
    with make_client() as client:
        wrong_extension = upload(
            client, b"hello", filename="notes.txt", content_type="text/plain"
        )
        assert wrong_extension.status_code == 415

        wrong_mime = upload(
            client, sample_pdf_bytes, filename="sample.pdf", content_type="text/plain"
        )
        assert wrong_mime.status_code == 415
        assert wrong_mime.json()["error"]["code"] == "unsupported_media_type"


def test_rejects_bad_magic_bytes() -> None:
    with make_client() as client:
        response = upload(client, b"this is not actually a pdf")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_pdf"


def test_rejects_page_limit(sample_pdf_bytes: bytes) -> None:
    with make_client(max_pages=1) as client:
        response = upload(client, sample_pdf_bytes)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "page_limit_exceeded"


def test_rejects_encrypted_pdf(encrypted_pdf_bytes: bytes) -> None:
    with make_client() as client:
        response = upload(client, encrypted_pdf_bytes)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "encrypted_pdf"


def test_no_extractable_text_fails_job() -> None:
    with make_client() as client:
        response = upload(client, build_blank_pdf())
        assert response.status_code == 202
        job = client.get(f"/mindmaps/{response.json()['job_id']}")
        assert job.status_code == 422
        payload = job.json()
        assert payload["status"] == "failed"
        assert payload["error"]["code"] == "no_extractable_text"


def test_llm_failure_returns_502(sample_pdf_bytes: bytes) -> None:
    with make_client(FakeLLMClient(fail=True)) as client:
        response = upload(client, sample_pdf_bytes)
        assert response.status_code == 202
        job = client.get(f"/mindmaps/{response.json()['job_id']}")
        assert job.status_code == 502
        payload = job.json()
        assert payload["status"] == "failed"
        assert payload["error"]["code"] == "llm_error"


def test_unknown_job_and_not_ready_export(sample_pdf_bytes: bytes) -> None:
    with make_client() as client:
        missing = client.get("/mindmaps/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "job_not_found"

        pending = client.app.state.store.create("pending.pdf", "abc123")
        response = client.get(f"/mindmaps/{pending.job_id}/export")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "job_not_ready"

        missing_export = client.get("/mindmaps/nope/export")
        assert missing_export.status_code == 404


def test_request_validation_errors(sample_pdf_bytes: bytes) -> None:
    with make_client() as client:
        bad_depth = upload(client, sample_pdf_bytes, form={"max_depth": "abc"})
        assert bad_depth.status_code == 422
        assert bad_depth.json()["error"]["code"] == "validation_error"

        uploaded = upload(client, sample_pdf_bytes)
        job_id = uploaded.json()["job_id"]
        bad_format = client.get(f"/mindmaps/{job_id}/export?format=xml")
        assert bad_format.status_code == 422

        bad_language = upload(client, sample_pdf_bytes, form={"language": "not a language!"})
        assert bad_language.status_code == 422
        assert bad_language.json()["error"]["code"] == "invalid_language"


def test_cors_allows_configured_origin() -> None:
    with make_client(cors_origins=["http://localhost:5173"]) as client:
        response = client.options(
            "/mindmaps",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
