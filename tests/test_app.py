from fastapi.testclient import TestClient

from fieldnote import app as app_module

client = TestClient(app_module.app)


def test_ui_hides_backend_and_default_model_names():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "Claude Code" not in html
    assert "beam:cloud" not in html
    assert "Ollama" in html
    assert "Server default" in html


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_status(monkeypatch):
    monkeypatch.setattr(app_module, "available", lambda: True)
    monkeypatch.setattr(app_module, "backend_name", lambda: "claude")
    monkeypatch.setattr(app_module, "backend_available", lambda: True)
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["ollama_available"] is True
    assert data["backend"] == "claude"
    assert "model" in data
    assert "version" in data


def test_models(monkeypatch):
    monkeypatch.setattr(app_module, "list_models", lambda: ["qwen2.5:3b"])
    response = client.get("/api/models")
    assert response.json() == {"models": ["qwen2.5:3b"]}


def test_evidence(monkeypatch):
    monkeypatch.setattr(app_module, "collect_system", lambda: {"os": "Linux"})
    assert client.get("/api/evidence").json() == {"os": "Linux"}


def test_diagnose_success(monkeypatch):
    monkeypatch.setattr(app_module, "backend_name", lambda: "claude")
    monkeypatch.setattr(app_module, "backend_available", lambda: True)
    monkeypatch.setattr(app_module, "collect_system", lambda: {"os": "Linux"})

    async def fake_investigate(model, complaint, evidence, timeout=180):
        assert model == "test:model"
        assert complaint == "Slow PC"
        return {
            "analysis": "Looks fine.",
            "commands": [{"command": "uname -s", "allowed": True, "exit_code": 0, "output": "Linux"}],
        }

    monkeypatch.setattr(app_module, "investigate", fake_investigate)
    response = client.post("/api/diagnose", json={"complaint": "Slow PC", "model": "test:model"})
    assert response.status_code == 200
    data = response.json()
    assert data["analysis"] == "Looks fine."
    assert data["model"] == "test:model"
    assert data["backend"] == "claude"
    assert data["evidence"]["os"] == "Linux"
    assert data["commands"][0]["command"] == "uname -s"


def test_diagnose_can_disable_commands(monkeypatch):
    monkeypatch.setattr(app_module, "backend_name", lambda: "ollama")
    monkeypatch.setattr(app_module, "backend_available", lambda: True)
    monkeypatch.setattr(app_module, "collect_system", lambda: {"os": "Linux"})

    async def fake_analyse(model, complaint, evidence):
        return "No commands."

    monkeypatch.setattr(app_module, "analyse", fake_analyse)
    response = client.post(
        "/api/diagnose",
        json={"complaint": "Slow PC", "model": "test:model", "allow_commands": False},
    )
    assert response.status_code == 200
    assert response.json()["commands"] == []


def test_diagnose_rejects_bad_model(monkeypatch):
    monkeypatch.setattr(app_module, "backend_available", lambda: True)
    response = client.post("/api/diagnose", json={"complaint": "Slow PC", "model": "bad model!!"})
    assert response.status_code == 422


def test_diagnose_rejects_bad_dns(monkeypatch):
    monkeypatch.setattr(app_module, "backend_available", lambda: True)
    response = client.post("/api/diagnose", json={"complaint": "Slow PC", "dns_host": "bad host!"})
    assert response.status_code == 422


def test_diagnose_requires_backend(monkeypatch):
    monkeypatch.setattr(app_module, "backend_name", lambda: "ollama")
    monkeypatch.setattr(app_module, "backend_available", lambda: False)
    response = client.post("/api/diagnose", json={"complaint": "Slow PC"})
    assert response.status_code == 503


def test_diagnose_requires_model_service(monkeypatch):
    monkeypatch.setattr(app_module, "backend_name", lambda: "claude")
    monkeypatch.setattr(app_module, "backend_available", lambda: False)
    response = client.post("/api/diagnose", json={"complaint": "Slow PC"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "model service" in detail
    assert "Claude Code" not in detail


def test_diagnose_sanitizes_backend_errors(monkeypatch):
    monkeypatch.setattr(app_module, "backend_name", lambda: "claude")
    monkeypatch.setattr(app_module, "backend_available", lambda: True)
    monkeypatch.setattr(app_module, "collect_system", lambda: {"os": "Linux"})
    monkeypatch.setattr(app_module, "analyser_model", lambda: "beam:cloud")

    async def fake_investigate(*args, **kwargs):
        raise RuntimeError("Claude Code failed while using model 'beam:cloud'.")

    monkeypatch.setattr(app_module, "investigate", fake_investigate)
    response = client.post("/api/diagnose", json={"complaint": "Slow PC", "model": "test:model"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "Claude Code" not in detail
    assert "beam:cloud" not in detail
    assert "model service" in detail
    assert "default model" in detail
