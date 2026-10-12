import os

from strands.models.bedrock import BedrockModel
from strands.models.ollama import OllamaModel

import coach.llm as llm
from coach.config import Settings, get_settings, load_env_file
from coach.envfile import read_env, write_env
from coach.llm import build_model, model_name, ollama_status, pick_model

OLLAMA = Settings(provider="ollama")


def test_auto_prefers_the_4b_model_when_both_are_pulled():
    assert pick_model("auto", {"qwen3:1.7b", "qwen3:4b-instruct"}) == "qwen3:4b-instruct"


def test_auto_falls_back_to_the_small_model():
    assert pick_model("auto", {"qwen3:1.7b", "llama3.2:latest"}) == "qwen3:1.7b"


def test_auto_without_ollama_names_the_default():
    assert pick_model("auto", None) == "qwen3:4b-instruct"
    assert pick_model("auto", set()) == "qwen3:4b-instruct"


def test_explicit_model_is_used_as_given():
    assert pick_model("llama3.2", {"qwen3:1.7b"}) == "llama3.2"


def test_status_reports_the_model_auto_picked(monkeypatch):
    monkeypatch.setattr(llm, "installed_models", lambda host: {"qwen3:1.7b"})
    status = ollama_status(OLLAMA)
    assert status == {"reachable": True, "model_ready": True, "model": "qwen3:1.7b", "detail": "ok"}


def test_status_tells_you_what_to_pull(monkeypatch):
    monkeypatch.setattr(llm, "installed_models", lambda host: set())
    auto = ollama_status(OLLAMA)
    assert not auto["model_ready"] and "ollama pull qwen3:1.7b" in auto["detail"]
    explicit = ollama_status(Settings(provider="ollama", model_id="llama3.2"))
    assert explicit["detail"] == "Model missing. Run: ollama pull llama3.2"


def test_status_when_ollama_is_down(monkeypatch):
    monkeypatch.setattr(llm, "installed_models", lambda host: None)
    status = ollama_status(OLLAMA)
    assert status["reachable"] is False and "ollama serve" in status["detail"]


def test_model_name_reads_the_built_model_or_falls_back():
    class Built:
        def get_config(self):
            return {"model_id": "qwen3:1.7b"}

    assert model_name(Built(), "auto") == "qwen3:1.7b"
    assert model_name(object(), "auto") == "auto"


def test_bedrock_models_send_no_temperature_and_leave_room_to_reason():
    """Haiku 5.5 rejects temperature, and its hidden reasoning counts against max_tokens."""
    model = build_model(Settings(), "chat")
    assert isinstance(model, BedrockModel)
    config = model.get_config()
    assert config["model_id"] == "us.anthropic.claude-haiku-5-5"
    assert "temperature" not in config and config["max_tokens"] == 4096
    assert model.client.meta.region_name == "us-east-1"
    assert build_model(Settings(), "synthesis").get_config()["max_tokens"] == 8192


def test_ollama_models_keep_their_temperatures(monkeypatch):
    monkeypatch.setattr(llm, "supports_thinking", lambda host, model_id: True)
    model = build_model(Settings(provider="ollama", model_id="qwen3:1.7b"), "extract")
    assert isinstance(model, OllamaModel)
    config = model.get_config()
    assert (config["temperature"], config["max_tokens"], config["additional_args"]) == (0.0, 200, {"think": False})


def test_env_file_with_a_bom_still_loads(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_bytes("\ufeffCOACH_MODEL=qwen3:1.7b\nCOACH_MEMORY=local\n".encode("utf-8"))
    monkeypatch.delenv("COACH_MODEL", raising=False)
    try:
        load_env_file(env)
        assert os.environ["COACH_MODEL"] == "qwen3:1.7b"
    finally:
        os.environ.pop("COACH_MODEL", None)
        os.environ.pop("COACH_MEMORY", None)


def test_env_writer_merges_removes_and_never_writes_a_bom(tmp_path):
    env = tmp_path / ".env"
    write_env({"COACH_MODEL": "qwen3:1.7b", "AWS_REGION": "us-east-1"}, env)
    write_env({"COACH_MODEL": None, "COACH_MEMORY": "agentcore"}, env)
    assert read_env(env) == {"AWS_REGION": "us-east-1", "COACH_MEMORY": "agentcore"}
    assert not env.read_bytes().startswith(b"\xef\xbb\xbf")


def test_defaults_are_bedrock_haiku_and_auto_for_ollama(monkeypatch):
    monkeypatch.setattr("coach.config.load_env_file", lambda path=None: None)
    for key in ("COACH_PROVIDER", "COACH_BEDROCK_MODEL", "COACH_MODEL", "COACH_MAX_DOC_CHARS"):
        monkeypatch.delenv(key, raising=False)
    settings = get_settings()
    assert (settings.provider, settings.active_model_id, settings.max_doc_chars) == (
        "bedrock", "us.anthropic.claude-haiku-5-5", 40_000)
    monkeypatch.setenv("COACH_PROVIDER", "ollama")
    monkeypatch.setenv("COACH_MODEL", "  ")
    settings = get_settings()
    assert (settings.active_model_id, settings.max_doc_chars) == ("auto", 12_000)  # a laptop model reads less
