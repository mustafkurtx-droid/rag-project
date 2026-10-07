import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from finance_rag.config import load_settings
from finance_rag.conversion import MarkerConverter
from finance_rag.embeddings import E5Embedder


def test_worker_command_and_real_pagination_parser(settings, tmp_path, monkeypatch):
    output = tmp_path / "converted"
    output.mkdir()
    pdf = tmp_path / "input.pdf"
    settings.marker_python = "separate-marker-python"
    settings.marker_device = "cpu"
    settings.model_cache_dir = tmp_path / "model-cache"
    monkeypatch.setenv("SURYA_INFERENCE_BACKEND", "llamacpp")
    monkeypatch.setenv("SURYA_INFERENCE_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.setenv("LLAMA_CPP_BINARY", "llama-server")

    def run(command, **kwargs):
        assert command[0] == "separate-marker-python"
        assert command[1].endswith("marker_worker.py")
        assert "--force-ocr" in command
        assert kwargs["stdout"].name.endswith("marker.log")
        assert kwargs["stderr"] == subprocess.STDOUT
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["timeout"] == settings.marker_timeout_seconds
        assert command[command.index("--device") + 1] == "cpu"
        assert "SURYA_INFERENCE_BACKEND" not in kwargs["env"]
        assert "LLAMA_CPP_BINARY" not in kwargs["env"]
        assert "SURYA_INFERENCE_URL" not in kwargs["env"]
        assert kwargs["env"]["MODEL_CACHE_DIR"] == str(settings.model_cache_dir / "marker")
        assert (
            kwargs["env"]["TEMP"] == kwargs["env"]["TMP"] == str(settings.model_cache_dir / "tmp")
        )
        (output / "document.md").write_text("{0}" + "-" * 48 + "\n\n# Risk\n\n-2.5%")
        (output / "document_meta.json").write_text(json.dumps({"page_stats": [{"page_id": 0}]}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    pages = MarkerConverter(settings).convert(pdf, output, force_ocr=True)
    assert pages[0].number == 1 and "-2.5%" in pages[0].markdown


def test_worker_timeout_is_explicit(settings, tmp_path, monkeypatch):
    def run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError, match="timed out"):
        MarkerConverter(settings).convert(tmp_path / "input.pdf", tmp_path)


class RecordingModel:
    max_seq_length = 512
    tokenizer = SimpleNamespace(encode=lambda text, **kwargs: text.split())

    def encode(self, inputs, **kwargs):
        self.inputs = inputs
        assert kwargs["normalize_embeddings"]
        assert not kwargs["show_progress_bar"]
        return SimpleNamespace(tolist=lambda: [[1.0, 0.0] for _ in inputs])


def test_e5_prefixes_and_no_silent_truncation():
    embedder = E5Embedder("intfloat/multilingual-e5-base", "cpu")
    embedder._model = model = RecordingModel()
    embedder.encode(["piyasa riski"], query=True)
    assert model.inputs == ["query: piyasa riski"]
    embedder.encode(["Expected Shortfall"])
    assert model.inputs == ["passage: Expected Shortfall"]
    with pytest.raises(ValueError, match="token limit"):
        embedder.encode(["word " * 512])


def test_mcp_env_file_works_from_another_directory(tmp_path, monkeypatch):
    env_file = tmp_path / "project.env"
    env_file.write_text("FINRAG_MARKER_PYTHON=C:/custom/python.exe\n")
    monkeypatch.setenv("FINRAG_ENV_FILE", str(env_file))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert load_settings().marker_python == "C:/custom/python.exe"


def test_worker_rejects_server_based_marker_before_loading_models(monkeypatch, tmp_path):
    from finance_rag import marker_worker

    monkeypatch.setattr("sys.argv", ["worker", "input.pdf", str(tmp_path)])
    monkeypatch.setattr(marker_worker, "version", lambda _: "2.0.0")
    with pytest.raises(RuntimeError, match="server-free"):
        marker_worker.main()


def test_native_worker_keeps_ocr_and_disables_optional_llm(monkeypatch, tmp_path):
    from finance_rag import marker_worker

    calls = {}
    models = {"native": object()}

    def create_models(**kwargs):
        calls["models"] = kwargs
        return models

    class Converter:
        def __init__(self, artifact_dict, config):
            assert artifact_dict is models
            calls["config"] = config

        def __call__(self, pdf):
            calls["pdf"] = pdf
            return "rendered"

    def save(rendered, output, name):
        calls["save"] = (rendered, output, name)

    monkeypatch.setattr(sys, "argv", ["worker", "input.pdf", str(tmp_path), "--force-ocr"])
    monkeypatch.setattr(marker_worker, "version", lambda _: "1.10.1")
    monkeypatch.setitem(
        sys.modules, "marker.converters.pdf", SimpleNamespace(PdfConverter=Converter)
    )
    monkeypatch.setitem(
        sys.modules, "marker.models", SimpleNamespace(create_model_dict=create_models)
    )
    monkeypatch.setitem(sys.modules, "marker.output", SimpleNamespace(save_output=save))
    marker_worker.main()
    assert calls["models"] == {"device": "cpu"}
    assert calls["config"]["force_ocr"] is True
    assert calls["config"]["use_llm"] is False
    assert not calls["config"].get("disable_ocr", False)
    assert calls["config"]["paginate_output"] is True
    assert json.loads((tmp_path / "conversion.json").read_text())["engine"] == "native-pytorch"
    assert models == {}
