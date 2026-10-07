"""Page/heading/block-aware chunks; repeat headers when splitting large tables."""

import re
from collections.abc import Callable

from .models import Chunk, Page


def blocks(text: str):
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        start = i
        if re.match(r"^#{1,6}\s", line):
            yield "heading", line
            i += 1
            continue
        stripped = line.strip()
        if stripped.startswith(("```", "~~~", "$$", "\\[")):
            delimiter = (
                stripped[:3]
                if stripped.startswith(("```", "~~~"))
                else ("$$" if stripped.startswith("$$") else "\\]")
            )
            kind = "code" if delimiter in ("```", "~~~") else "equation"
            i += 1
            if not (kind == "equation" and len(stripped) > 2 and stripped.endswith(delimiter)):
                while i < len(lines):
                    close = lines[i].strip().endswith(delimiter)
                    i += 1
                    if close:
                        break
        elif stripped.startswith("|"):
            kind = "table"
            i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                i += 1
        else:
            kind = "text"
            i += 1
            while i < len(lines) and lines[i].strip():
                if re.match(r"^(#{1,6}\s|\||```|~~~|\$\$|\\\[)", lines[i]):
                    break
                i += 1
        yield kind, "\n".join(lines[start:i])


def split_text(text: str, fits: Callable[[str], bool]) -> list[str]:
    parts = []
    while text:
        if fits(text):
            parts.append(text)
            break
        lo, hi = 1, len(text)
        while lo < hi:
            middle = (lo + hi + 1) // 2
            if fits(text[:middle]):
                lo = middle
            else:
                hi = middle - 1
        if not fits(text[:lo]):
            raise ValueError("Chunk budget too small for section context.")
        cut = max(text.rfind("\n", 0, lo), text.rfind(" ", 0, lo))
        cut = cut if cut > lo // 2 else lo
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    return parts


def make_chunks(
    document_id: str, pages: list[Page], count: Callable[[str], int], budget: int
) -> list[Chunk]:
    chunks: list[Chunk] = []
    headings: list[tuple[int, str]] = []

    def section():
        return " > ".join(value for _, value in headings)

    for page in pages:
        pending = ""

        def context(text):
            # Bound heading context without truncating the stored citation heading.
            heading = section()
            while heading and count(heading) > budget // 4:
                heading = heading[: max(0, len(heading) // 2)]
            return f"{heading}\n\n{text}".strip()

        def fits(text):
            return count(context(text)) <= budget

        def emit(text, kind, fragmented=False, page=page):
            if text.strip():
                chunks.append(
                    Chunk(
                        id=f"{document_id}:{page.number}:{len(chunks)}",
                        document_id=document_id,
                        page=page.number,
                        section=section(),
                        kind=kind,
                        text=text,
                        embedding_text=context(text),
                        fragmented=fragmented,
                    )
                )

        for kind, text in blocks(page.markdown):
            if kind == "heading":
                emit(pending, "text")
                pending = ""
                level = len(text) - len(text.lstrip("#"))
                headings = [(n, h) for n, h in headings if n < level]
                headings.append((level, text[level:].strip()))
                # Headings themselves are searchable, including heading-only pages.
                for part in split_text(text, fits):
                    emit(part, "heading")
                continue
            if kind == "text" and fits((pending + "\n\n" + text).strip()):
                pending = (pending + "\n\n" + text).strip()
                continue
            emit(pending, "text")
            pending = ""
            if fits(text):
                emit(text, kind)
            elif kind == "table":
                rows = text.splitlines()
                header = "\n".join(rows[:2])
                if len(rows) > 2 and all(fits(header + "\n" + row) for row in rows[2:]):
                    current = header
                    for row in rows[2:]:
                        if not fits(current + "\n" + row):
                            emit(current, kind, True)
                            current = header
                        current += "\n" + row
                    emit(current, kind, True)
                else:
                    for part in split_text(text, fits):
                        emit(part, kind, True)
            else:
                for part in split_text(text, fits):
                    emit(part, kind, True)
        emit(pending, "text")
    return chunks
