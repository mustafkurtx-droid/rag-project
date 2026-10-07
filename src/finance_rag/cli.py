import argparse
import json
import logging

from .config import load_settings
from .models import DocumentMetadata, SearchFilters
from .service import FinanceRAG, doctor


def main() -> None:
    parser = argparse.ArgumentParser(description="Finance RAG local CLI")
    parser.add_argument("--data-dir")
    parser.add_argument("--pdf-dir")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Inspect installation without loading model weights")
    commands.add_parser("list")
    add = commands.add_parser("add", help="Convert and index a PDF synchronously")
    add.add_argument("pdf")
    add.add_argument("--metadata", help="Path to a UTF-8 JSON document metadata file")
    add.add_argument("--force-ocr", action="store_true")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--mode", choices=["hybrid", "semantic", "keyword"], default="hybrid")
    search.add_argument("--top-k", type=int, default=5)
    search.add_argument("--domain")
    search.add_argument("--as-of")
    page = commands.add_parser("page")
    page.add_argument("document_id")
    page.add_argument("number", type=int)
    page.add_argument("--offset", type=int, default=0)
    remove = commands.add_parser("remove")
    remove.add_argument("document_id")
    commands.add_parser("serve", help="Run the stdio MCP server")
    args = parser.parse_args()
    overrides = {
        key: value
        for key, value in {"data_dir": args.data_dir, "allowed_pdf_dir": args.pdf_dir}.items()
        if value is not None
    }
    settings = load_settings(**overrides)
    logging.basicConfig(level=logging.INFO)
    if args.command == "doctor":
        print(json.dumps(doctor(settings), ensure_ascii=False, indent=2))
        return
    if args.command == "serve":
        from .embeddings import prepare_native_libraries
        from .server import create_server

        prepare_native_libraries()
        create_server(settings).run(transport="stdio", show_banner=False)
        return
    from .embeddings import prepare_native_libraries

    prepare_native_libraries()
    rag = FinanceRAG(settings)
    try:
        if args.command == "add":
            from pathlib import Path

            metadata = (
                DocumentMetadata.model_validate_json(
                    Path(args.metadata).read_text(encoding="utf-8-sig")
                )
                if args.metadata
                else DocumentMetadata()
            )
            result = rag.add(args.pdf, metadata, args.force_ocr)
        elif args.command == "search":
            result = rag.search(
                args.query,
                SearchFilters(domain=args.domain, as_of=args.as_of),
                args.top_k,
                args.mode,
            )
        elif args.command == "page":
            if args.number < 1 or args.offset < 0:
                parser.error("page >= 1 and offset >= 0 are required")
            result = rag.get_page(args.document_id, args.number, args.offset)
        elif args.command == "remove":
            result = rag.remove(args.document_id)
        else:
            result = rag.store.list_documents()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        rag.close()


if __name__ == "__main__":
    main()
