import json
import time
from datetime import date

import pytest
from conftest import FakeConverter, FakeEmbedder

from finance_rag.models import DocumentMetadata, SearchFilters
from finance_rag.service import FinanceRAG


def test_real_chroma_fts_lifecycle_and_idempotency(rag, pdf):
    added = rag.add(str(pdf), DocumentMetadata(domain="risk", publication_date="2024-01-01"))
    assert added["status"] == "success"
    again = rag.add(str(pdf), DocumentMetadata(domain="economics"))
    assert again["status"] == "already_exists" and again["domain"] == "risk"
    assert rag.converter.calls == 1
    for mode in ("hybrid", "semantic", "keyword"):
        result = rag.search("Expected shortfall", SearchFilters(domain="risk"), mode=mode)
        assert result["count"] > 0
        assert all(item["page"] in (1, 2) and item["citation"] for item in result["results"])
    page = rag.get_page(added["document_id"], 2)
    assert "-1.234,56 TRY" in page["markdown"]
    first = rag.get_page(added["document_id"], 2, limit=15)
    second = rag.get_page(added["document_id"], 2, offset=first["next_offset"])
    assert first["markdown"] + second["markdown"] == page["markdown"]
    rag.remove(added["document_id"])
    assert rag.store.collection.count() == 0
    assert rag.search("VaR", SearchFilters())["results"] == []
    assert (rag.settings.data_dir / "documents" / added["document_id"] / "source.pdf").exists()


def test_publication_cutoff_applies_to_dense_and_lexical(rag, pdf):
    for index, publication in enumerate(("2020-01-01", "2025-01-01", None)):
        pdf.write_bytes(f"%PDF-1.7\n{index}".encode())
        rag.add(str(pdf), DocumentMetadata(publication_date=publication, domain="risk"))
    for mode in ("hybrid", "semantic", "keyword"):
        result = rag.search("VaR", SearchFilters(as_of=date(2022, 1, 1)), top_k=20, mode=mode)
        assert result["count"] > 0
        assert all(r["publication_date"] == "2020-01-01" for r in result["results"])
        assert rag.search("VaR", SearchFilters(domain="economics"), mode=mode)["count"] == 0


def test_path_boundary_and_signature(rag, tmp_path):
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-test")
    with pytest.raises(ValueError, match="inside"):
        rag.add(str(outside), DocumentMetadata())
    invalid = rag.settings.allowed_pdf_dir / "invalid.pdf"
    invalid.write_text("not a PDF")
    with pytest.raises(ValueError, match="signature"):
        rag.add(str(invalid), DocumentMetadata())


def test_failed_conversion_rolls_back_and_retry_succeeds(rag, pdf):
    rag.converter.fail = True
    with pytest.raises(RuntimeError, match="OCR"):
        rag.add(str(pdf), DocumentMetadata())
    assert rag.store.list_documents()["count"] == 0
    assert rag.store.collection.count() == 0
    rag.converter.fail = False
    assert rag.add(str(pdf), DocumentMetadata())["status"] == "success"


def test_partial_vector_write_rolls_back(rag, pdf, monkeypatch):
    original = rag.store.publish

    def fail(document, chunks, vectors):
        rag.store.collection.upsert(
            ids=[chunks[0].id],
            embeddings=[vectors[0]],
            metadatas=[{"document_id": document["document_id"]}],
        )
        raise RuntimeError("disk failure")

    monkeypatch.setattr(rag.store, "publish", fail)
    with pytest.raises(RuntimeError, match="disk failure"):
        rag.add(str(pdf), DocumentMetadata())
    assert rag.store.collection.count() == 0
    monkeypatch.setattr(rag.store, "publish", original)
    assert rag.add(str(pdf), DocumentMetadata())["status"] == "success"


def test_jobs_report_success_and_errors(rag, pdf):
    job = rag.submit(str(pdf), DocumentMetadata())
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = rag.store.job(job["job_id"])
        if status["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.01)
    assert status["status"] == "succeeded"
    assert status["result"]["document_id"]


def test_restart_recovers_and_preserves_ready_documents(settings):
    rag = FinanceRAG(settings, converter=FakeConverter(), embedder=FakeEmbedder())
    pdf = settings.allowed_pdf_dir / "a.pdf"
    pdf.write_bytes(b"%PDF-1.7\nmock")
    added = rag.add(str(pdf), DocumentMetadata())
    rag.store.begin({"document_id": "incomplete"})
    rag.store.collection.upsert(
        ids=["bad"], embeddings=[[0.0] * 64], metadatas=[{"document_id": "incomplete"}]
    )
    rag.store.save_job({"job_id": "stopped", "status": "running"})
    rag.close()
    reopened = FinanceRAG(settings, converter=FakeConverter(), embedder=FakeEmbedder())
    try:
        assert reopened.store.document(added["document_id"])
        assert reopened.store.document("incomplete", ready_only=False) is None
        assert reopened.store.collection.get(ids=["bad"])["ids"] == []
        assert reopened.store.job("stopped")["status"] == "interrupted"
        assert reopened.search("shortfall", SearchFilters(), mode="keyword")["count"] > 0
    finally:
        reopened.close()


def test_model_mismatch_is_rejected(settings):
    rag = FinanceRAG(settings, converter=FakeConverter(), embedder=FakeEmbedder())
    rag.close()
    settings.embedding_model = "intfloat/multilingual-e5-small"
    with pytest.raises(ValueError, match="Embedding model differs"):
        FinanceRAG(settings, converter=FakeConverter(), embedder=FakeEmbedder())


def test_second_process_owner_rejected(rag):
    with pytest.raises(RuntimeError, match="already in use"):
        FinanceRAG(rag.settings, converter=FakeConverter(), embedder=FakeEmbedder())


def test_fts_query_syntax_is_data(rag, pdf):
    rag.add(str(pdf), DocumentMetadata())
    result = rag.search('" OR * NOT VaR; DROP TABLE documents', SearchFilters(), mode="keyword")
    assert isinstance(result["results"], list)
    assert rag.store.list_documents()["count"] == 1
    json.dumps(result)
