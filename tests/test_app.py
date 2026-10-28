from fastapi.testclient import TestClient

from fieldnote import app as app_module

client = TestClient(app_module.app)


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_status(monkeypatch):
    monkeypatch.setattr(app_module, "available", lambda: True)
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["ollama_available"] is True
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
    monkeypatch.setattr(app_module, "available", lambda: True)
    monkeypatch.setattr(app_module, "collect_system", lambda: {"os": "Linux"})

    async def fake_analyse(model, complaint, evidence):
        assert model == "test:model"
        assert complaint == "Slow PC"
        return "Looks fine."

    monkeypatch.setattr(app_module, "analyse", fake_analyse)
    response = client.post(
        "/api/diagnose", json={"complaint": "Slow PC", "model": "test:model"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["analysis"] == "Looks fine."
    assert data["model"] == "test:model"
    assert data["evidence"]["os"] == "Linux"


def test_diagnose_rejects_bad_model(monkeypatch):
    monkeypatch.setattr(app_module, "available", lambda: True)
    response = client.post(
        "/api/diagnose", json={"complaint": "Slow PC", "model": "bad model!!"}
    )
    assert response.status_code == 422


def test_diagnose_rejects_bad_dns(monkeypatch):
    monkeypatch.setattr(app_module, "available", lambda: True)
    response = client.post(
        "/api/diagnose", json={"complaint": "Slow PC", "dns_host": "bad host!"}
    )
    assert response.status_code == 422


def test_diagnose_requires_ollama(monkeypatch):
    monkeypatch.setattr(app_module, "available", lambda: False)
    response = client.post("/api/diagnose", json={"complaint": "Slow PC"})
    assert response.status_code == 503
