# Upstream references

The `finance_rag` application is a new implementation informed by the tool names
and modular structure of the downloaded PDF RAG MCP Server project (`pdfrag-main`).
Its original MIT license and copyright notice remain in `pdfrag-main/LICENSE`.
No upstream repository files were modified.

Marker is used through its public Python API and is not copied into the application.
The downloaded Marker 2 source is in `marker-master` and is retained as a reference.
The active runtime uses marker-pdf 1.10.1 in a separate Python environment to run
native OCR without an inference server. Version 1.10.1 declares GPL-3.0-or-later;
its code and model-weight licenses differ from the downloaded Marker 2 snapshot.
See https://github.com/datalab-to/marker/blob/v1.10.1/pyproject.toml and its README
for the actual runtime's notices and model-weight terms.

Chroma, FastMCP, Sentence Transformers, multilingual E5, Surya and other dependencies
retain their respective upstream licenses. No model weights are bundled in this project.
