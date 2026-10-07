import importlib
import os
import threading
from pathlib import Path


def prepare_native_libraries() -> None:
    """Initialize BLAS before Chroma starts native threads on Windows.

    First importing SciPy inside a query thread after opening a persisted index
    can hang in the Windows DLL loader. This imports no model and downloads nothing.
    """
    importlib.import_module("scipy.linalg")


class E5Embedder:
    """One local multilingual E5 instance, loaded only when actually needed."""

    def __init__(
        self,
        model: str,
        device: str,
        cache_dir: Path | None = None,
        disable_xet: bool = False,
        local_files_only: bool = False,
    ):
        if "multilingual-e5" not in model:
            raise ValueError(
                "This adapter requires a multilingual-e5 model with query/passage prefixes."
            )
        self.model_name = model
        self.device = device
        self.cache_dir = cache_dir
        self.disable_xet = disable_xet
        self.local_files_only = local_files_only
        self._model = None
        self._lock = threading.RLock()

    def _load(self):
        with self._lock:
            if self._model is None:
                if self.local_files_only:
                    # Also block ancillary Hub metadata requests made during imports.
                    os.environ["HF_HUB_OFFLINE"] = "1"
                if self.disable_xet:
                    os.environ["HF_HUB_DISABLE_XET"] = "1"
                if self.cache_dir is not None:
                    os.environ["HF_XET_CACHE"] = str(self.cache_dir.parent / "xet")
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(
                    self.model_name,
                    device=self.device,
                    cache_folder=str(self.cache_dir) if self.cache_dir is not None else None,
                    local_files_only=self.local_files_only,
                )
            return self._model

    def count(self, text: str) -> int:
        model = self._load()
        return len(model.tokenizer.encode("passage: " + text, add_special_tokens=True))

    def encode(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        with self._lock:
            model = self._load()
            prefix = "query: " if query else "passage: "
            inputs = [prefix + text for text in texts]
            limit = min(512, model.max_seq_length)
            if any(len(model.tokenizer.encode(t)) > limit for t in inputs):
                raise ValueError(
                    "Embedding input exceeds the model token limit; shorten the input."
                )
            return model.encode(
                inputs,
                batch_size=16,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            ).tolist()
