"""Chroma vectors plus an authoritative SQLite catalog and FTS5 lexical index."""

import json
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from .models import Chunk, SearchFilters


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, root: Path, model_name: str):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(root / "catalog.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                id UNINDEXED, text, tokenize='unicode61 remove_diacritics 2'
            );
            CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)
        self.client = chromadb.PersistentClient(
            path=str(root / "chroma"), settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            "finance_chunks_v1",
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
            metadata={"embedding_model": model_name, "schema_version": 1},
        )
        if self.collection.metadata.get("embedding_model") != model_name:
            self.db.close()
            raise ValueError(
                "Embedding model differs from the stored index. Use a new data directory."
            )

    def recover(self) -> None:
        with self.lock:
            rows = self.db.execute("SELECT id FROM documents WHERE state != 'ready'").fetchall()
            for row in rows:
                self.remove(row["id"])
            for row in self.db.execute("SELECT id, payload FROM jobs").fetchall():
                job = json.loads(row["payload"])
                if job["status"] in {"queued", "running"}:
                    job.update(status="interrupted", error="Server stopped. Submit this PDF again.")
                    self.save_job(job)

    def save_job(self, job: dict) -> None:
        with self.lock, self.db:
            job["updated_at"] = now()
            self.db.execute(
                "INSERT OR REPLACE INTO jobs VALUES (?, ?)",
                (job["job_id"], json.dumps(job, ensure_ascii=False)),
            )

    def job(self, job_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise ValueError("Unknown job_id.")
            return json.loads(row[0])

    def pending_jobs(self) -> int:
        with self.lock:
            return self.db.execute(
                "SELECT count(*) FROM jobs WHERE json_extract(payload, '$.status') "
                "IN ('queued', 'running')"
            ).fetchone()[0]

    def document(self, document_id: str, *, ready_only: bool = True) -> dict | None:
        with self.lock:
            row = self.db.execute(
                "SELECT state, payload FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            if row is None or (ready_only and row["state"] != "ready"):
                return None
            return json.loads(row["payload"])

    def list_documents(self, limit: int = 100, offset: int = 0) -> dict:
        with self.lock:
            total = self.db.execute(
                "SELECT count(*) FROM documents WHERE state='ready'"
            ).fetchone()[0]
            rows = self.db.execute(
                "SELECT payload FROM documents WHERE state='ready' ORDER BY id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return {
                "count": total,
                "documents": [json.loads(r[0]) for r in rows],
                "next_offset": offset + limit if offset + limit < total else None,
            }

    def begin(self, document: dict) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO documents VALUES (?, 'indexing', ?)",
                (document["document_id"], json.dumps(document, ensure_ascii=False)),
            )

    def publish(self, document: dict, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("Embedding count does not match chunk count.")
        with self.lock:
            metadata = {
                "document_id": document["document_id"],
                **{
                    key: document[key]
                    for key in ("domain", "institution", "geography", "risk_type")
                },
                "publication_day": document["publication_day"],
            }
            size = min(128, self.client.get_max_batch_size())
            for start in range(0, len(chunks), size):
                batch = chunks[start : start + size]
                self.collection.upsert(
                    ids=[c.id for c in batch],
                    embeddings=vectors[start : start + size],
                    documents=[c.text for c in batch],
                    metadatas=[
                        {
                            **metadata,
                            "page": c.page,
                            "section": c.section,
                            "kind": c.kind,
                            "fragmented": c.fragmented,
                        }
                        for c in batch
                    ],
                )
            # Publish in SQLite only after every vector batch succeeds.
            with self.db:
                for chunk in chunks:
                    self.db.execute(
                        "INSERT INTO chunks VALUES (?, ?, ?)",
                        (chunk.id, chunk.document_id, chunk.model_dump_json()),
                    )
                    self.db.execute(
                        "INSERT INTO chunks_fts VALUES (?, ?)", (chunk.id, chunk.embedding_text)
                    )
                self.db.execute(
                    "UPDATE documents SET state='ready', payload=? WHERE id=?",
                    (json.dumps(document, ensure_ascii=False), document["document_id"]),
                )

    def remove(self, document_id: str) -> int:
        with self.lock:
            count = self.db.execute(
                "SELECT count(*) FROM chunks WHERE document_id=?", (document_id,)
            ).fetchone()[0]
            with self.db:
                self.db.execute("UPDATE documents SET state='deleting' WHERE id=?", (document_id,))
            self.collection.delete(where={"document_id": document_id})
            with self.db:
                self.db.execute(
                    "DELETE FROM chunks_fts WHERE id IN "
                    "(SELECT id FROM chunks WHERE document_id=?)",
                    (document_id,),
                )
                self.db.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
                self.db.execute("DELETE FROM documents WHERE id=?", (document_id,))
            return count

    @staticmethod
    def where(filters: SearchFilters) -> dict | None:
        clauses = [
            {key: {"$eq": value}}
            for key, value in filters.model_dump().items()
            if key != "as_of" and value is not None
        ]
        if filters.as_of:
            clauses.extend(
                [
                    {"publication_day": {"$gt": 0}},
                    {"publication_day": {"$lte": filters.as_of.toordinal()}},
                ]
            )
        return {"$and": clauses} if len(clauses) > 1 else (clauses[0] if clauses else None)

    def semantic(self, vector: list[float], filters: SearchFilters, limit: int) -> list[tuple]:
        with self.lock:
            if not self.collection.count():
                return []
            result = self.collection.query(
                query_embeddings=[vector],
                n_results=min(limit, self.collection.count()),
                where=self.where(filters),
                include=["distances"],
            )
            return list(zip(result["ids"][0], result["distances"][0], strict=True))

    def lexical(self, query: str, filters: SearchFilters, limit: int) -> list[tuple]:
        # Tokenize instead of exposing FTS query syntax to callers.
        terms = list(dict.fromkeys(re.findall(r"[^\W_]+", query.casefold(), re.UNICODE)))[:40]
        if not terms:
            return []
        match = " OR ".join('"' + term + '"' for term in terms)
        clauses = ["chunks_fts MATCH ?", "d.state='ready'"]
        values: list = [match]
        for key, value in filters.model_dump().items():
            if key == "as_of" or value is None:
                continue
            if key == "document_id":
                clauses.append("d.id=?")
            else:
                # key is drawn exclusively from the validated SearchFilters schema.
                clauses.append(f"json_extract(d.payload, '$.{key}')=?")
            values.append(value)
        if filters.as_of:
            clauses.append("json_extract(d.payload, '$.publication_day') BETWEEN 1 AND ?")
            values.append(filters.as_of.toordinal())
        with self.lock:
            rows = self.db.execute(
                "SELECT c.id, bm25(chunks_fts) AS score FROM chunks_fts "
                "JOIN chunks c ON c.id=chunks_fts.id JOIN documents d ON d.id=c.document_id "
                f"WHERE {' AND '.join(clauses)} ORDER BY score, c.id LIMIT ?",
                [*values, limit],
            ).fetchall()
            return [(row[0], row[1]) for row in rows]

    def evidence(self, chunk_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute(
                "SELECT c.payload, d.payload FROM chunks c JOIN documents d ON d.id=c.document_id "
                "WHERE c.id=? AND d.state='ready'",
                (chunk_id,),
            ).fetchone()
            if row is None:
                return None
            chunk, document = json.loads(row[0]), json.loads(row[1])
            chunk.pop("embedding_text")
            return {
                **chunk,
                "title": document["title"],
                "filename": document["filename"],
                "publication_date": document["publication_date"],
                "source_url": document["source_url"],
                "domain": document["domain"],
                "citation": f"[{document['title']}, PDF s. {chunk['page']}, {chunk_id}]",
            }

    def close(self) -> None:
        self.db.close()
