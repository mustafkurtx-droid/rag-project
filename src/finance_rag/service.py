import hashlib
import json
import logging
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from filelock import FileLock, Timeout

from .chunking import make_chunks
from .config import Settings
from .conversion import MarkerConverter
from .embeddings import E5Embedder
from .models import DocumentMetadata, SearchFilters
from .retrieval import search
from .storage import Store, now

logger = logging.getLogger(__name__)


class FinanceRAG:
    def __init__(self, settings: Settings, *, converter=None, embedder=None):
        settings.prepare()
        self.settings = settings
        self._process_lock = FileLock(settings.data_dir / "service.lock", thread_local=False)
        try:
            self._process_lock.acquire(timeout=0)
        except Timeout as exc:
            raise RuntimeError(
                "This data directory is already in use. Use the running MCP server."
            ) from exc
        try:
            self.store = Store(settings.data_dir, settings.embedding_model)
            self.store.recover()
            self.converter = converter or MarkerConverter(settings)
            self.embedder = embedder or E5Embedder(
                settings.embedding_model,
                settings.embedding_device,
                settings.model_cache_dir / "huggingface" if settings.model_cache_dir else None,
                disable_xet=settings.embedding_disable_xet,
                local_files_only=settings.embedding_local_files_only,
            )
            self._jobs_lock = threading.Lock()
            self._ingestion_lock = threading.Lock()
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdf-ingestion")
        except Exception:
            self._process_lock.release()
            raise

    def validate_pdf(self, path: str) -> Path:
        pdf = Path(path).expanduser().resolve(strict=True)
        if not pdf.is_relative_to(self.settings.allowed_pdf_dir):
            raise ValueError(
                "PDF must be inside FINRAG_ALLOWED_PDF_DIR (including resolved symlinks)."
            )
        if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
            raise ValueError("A local .pdf file is required.")
        if pdf.stat().st_size > self.settings.max_pdf_mb * 1024 * 1024:
            raise ValueError("PDF exceeds FINRAG_MAX_PDF_MB.")
        with pdf.open("rb") as stream:
            if b"%PDF-" not in stream.read(1024):
                raise ValueError("File has no PDF signature.")
        return pdf

    def add(self, path: str, metadata: DocumentMetadata, force_ocr: bool = False) -> dict:
        """Synchronous CLI entry; MCP uses submit() to avoid long request timeouts."""
        with self._ingestion_lock:
            pdf = self.validate_pdf(path)
            staging = self.settings.data_dir / f"snapshot-{uuid.uuid4().hex}.pdf"
            try:
                digest = hashlib.sha256()
                total = 0
                with pdf.open("rb") as source, staging.open("wb") as target:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        total += len(block)
                        if total > self.settings.max_pdf_mb * 1024 * 1024:
                            raise ValueError("PDF grew beyond the configured size limit.")
                        digest.update(block)
                        target.write(block)
                document_id = digest.hexdigest()
                if existing := self.store.document(document_id):
                    return {
                        "status": "already_exists",
                        **existing,
                        "notice": "Existing metadata preserved; remove and re-add to change it.",
                    }
                output = self.settings.data_dir / "documents" / document_id
                output.mkdir(parents=True, exist_ok=True)
                document = {
                    **metadata.model_dump(mode="json"),
                    "document_id": document_id,
                    "title": metadata.title or pdf.stem,
                    "filename": pdf.name,
                    "publication_day": metadata.publication_date.toordinal()
                    if metadata.publication_date
                    else 0,
                    "added_at": now(),
                    "artifact_dir": str(output),
                    "embedding_model": self.settings.embedding_model,
                    "chunk_tokens": self.settings.chunk_tokens,
                }
                self.store.begin(document)
                try:
                    staging.replace(output / "source.pdf")
                    pages = self.converter.convert(output / "source.pdf", output, force_ocr)
                    if not any(page.markdown.strip() for page in pages):
                        raise ValueError("Marker produced no text; check OCR and the source PDF.")
                    (output / "pages.json").write_text(
                        json.dumps([p.model_dump() for p in pages], ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    chunks = make_chunks(
                        document_id, pages, self.embedder.count, self.settings.chunk_tokens
                    )
                    if not chunks:
                        raise ValueError("No indexable chunks were produced.")
                    vectors = self.embedder.encode([chunk.embedding_text for chunk in chunks])
                    document.update(
                        pages=len(pages),
                        chunks=len(chunks),
                        fragmented_chunks=sum(c.fragmented for c in chunks),
                    )
                    (output / "manifest.json").write_text(
                        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    self.store.publish(document, chunks, vectors)
                except Exception:
                    self.store.remove(document_id)
                    raise
                return {"status": "success", **document}
            finally:
                staging.unlink(missing_ok=True)

    def submit(self, path: str, metadata: DocumentMetadata, force_ocr: bool = False) -> dict:
        pdf = self.validate_pdf(path)
        with self._jobs_lock:
            if self.store.pending_jobs() >= self.settings.max_pending_jobs:
                raise ValueError("Ingestion queue is full. Wait for an existing job to finish.")
            job = {
                "job_id": uuid.uuid4().hex,
                "status": "queued",
                "filename": pdf.name,
                "created_at": now(),
            }
            self.store.save_job(job)
            self._executor.submit(self._run_job, job["job_id"], str(pdf), metadata, force_ocr)
        return {
            "job_id": job["job_id"],
            "status": "queued",
            "next_step": "Call pdf_job_status with job_id until succeeded or failed.",
        }

    def _run_job(self, job_id: str, path: str, metadata: DocumentMetadata, force_ocr: bool):
        job = self.store.job(job_id)
        job["status"] = "running"
        self.store.save_job(job)
        try:
            job.update(result=self.add(path, metadata, force_ocr), status="succeeded")
        except Exception as exc:
            logger.exception("PDF ingestion failed: %s", job_id)
            job.update(status="failed", error=str(exc))
        self.store.save_job(job)

    def search(self, query: str, filters: SearchFilters, top_k: int = 5, mode="hybrid") -> dict:
        return search(self.store, self.embedder, query, filters, top_k, mode)

    def get_page(self, document_id: str, page: int, offset: int = 0, limit: int = 12000) -> dict:
        with self.store.lock:
            doc = self.store.document(document_id)
            if doc is None:
                raise ValueError("Unknown document_id.")
            pages = json.loads(
                (Path(doc["artifact_dir"]) / "pages.json").read_text(encoding="utf-8")
            )
            found = next((item for item in pages if item["number"] == page), None)
            if found is None:
                raise ValueError("Page not found; page numbers are one-based physical PDF pages.")
            text = found["markdown"]
            return {
                "document_id": document_id,
                "page": page,
                "title": doc["title"],
                "markdown": text[offset : offset + limit],
                "total_characters": len(text),
                "next_offset": offset + limit if offset + limit < len(text) else None,
                "source_pdf": str(Path(doc["artifact_dir"]) / "source.pdf"),
            }

    def remove(self, document_id: str) -> dict:
        with self._ingestion_lock, self.store.lock:
            if self.store.document(document_id) is None:
                raise ValueError("Unknown document_id.")
            count = self.store.remove(document_id)
        return {
            "status": "removed",
            "document_id": document_id,
            "removed_chunks": count,
            "notice": "Removed from both search indexes. Local conversion artifacts retained.",
        }

    def close(self) -> None:
        self._executor.shutdown(wait=True)
        self.store.close()
        self._process_lock.release()


def doctor(settings: Settings) -> dict:
    import importlib.metadata

    versions = {}
    for name in ("finance-rag-mcp", "fastmcp", "chromadb", "sentence-transformers"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed in this Python"
    marker_python = settings.marker_python or sys.executable
    try:
        inspection = subprocess.run(
            [
                marker_python,
                "-c",
                "import json, importlib.metadata as m; "
                "print(json.dumps({n:m.version(n) for n in "
                "['marker-pdf','surya-ocr','torch','transformers']}))",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if inspection.returncode:
            marker_runtime = {"status": "unavailable", "error": inspection.stderr[-1200:]}
        else:
            packages = json.loads(inspection.stdout)
            marker_runtime = {
                "status": "installed" if packages["marker-pdf"] == "1.10.1" else "wrong_version",
                "versions": packages,
            }
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        marker_runtime = {"status": "unavailable", "error": str(exc)}
    return {
        "versions": versions,
        "data_dir": str(settings.data_dir.resolve()),
        "allowed_pdf_dir": str(settings.allowed_pdf_dir.resolve()),
        "marker_python": marker_python,
        "marker_runtime": marker_runtime,
        "marker_engine": "native-pytorch",
        "external_inference_server_required": False,
        "embedding_model": settings.embedding_model,
        "model_cache_dir": str(settings.model_cache_dir) if settings.model_cache_dir else None,
        "notice": "Dependency inspection only; model weights and inference are not tested. "
        "Marker 1.10.1 runs OCR in the worker's Python process; no llama-server is required. "
        "OCR model weights are downloaded separately on first conversion.",
    }
