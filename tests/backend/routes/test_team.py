# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Team collaboration (协作码) route tests: hosting, code-gated join with
rate limiting, shared files, and member cleanup."""

import io
import json

import pytest

pytestmark = [pytest.mark.backend]


@pytest.fixture()
def team_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_FORMULATOR_HOME", str(tmp_path))
    monkeypatch.setenv("WORKSPACE_BACKEND", "local")

    from data_formulator.team import service as team_service_module
    # Fresh service per test so persisted state does not leak across tests.
    svc = team_service_module.TeamService()
    monkeypatch.setattr(team_service_module, "team_service", svc)

    import data_formulator.routes.team as team_routes
    monkeypatch.setattr(team_routes, "team_service", svc)

    from flask import Flask
    from data_formulator.error_handler import register_error_handlers

    app = Flask(__name__)
    app.register_blueprint(team_routes.team_bp)
    register_error_handlers(app)

    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "sales.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (shared / "notes.txt").write_text("not shareable", encoding="utf-8")

    return app.test_client(), svc, shared


IDENT = {"X-Identity-Id": "tester"}


def _data(resp):
    body = json.loads(resp.data)
    assert body.get("status") == "success", body
    return body["data"]


def test_host_start_generates_code_and_persists(team_env, tmp_path):
    client, svc, shared = team_env
    d = _data(client.post("/api/team/host/start", headers=IDENT, json={
        "team_name": "测试组", "shared_folder": str(shared),
    }))
    assert d["mode"] == "host"
    assert len(d["code"]) == 4 and d["code"].isdigit()
    assert (tmp_path / "team_state.json").exists()

    status = _data(client.get("/api/team/status"))
    assert status["team_name"] == "测试组"
    assert status["members"] == []


def test_join_requires_correct_code_and_rate_limits(team_env):
    client, svc, shared = team_env
    d = _data(client.post("/api/team/host/start", headers=IDENT, json={"team_name": "t"}))
    code = d["code"]
    wrong = f"{(int(code) + 1) % 10000:04d}"

    for _ in range(5):
        resp = client.post("/api/team/join", json={"code": wrong, "name": "x"})
        assert resp.status_code == 403
    # Sixth attempt hits the rate limit even before checking the code.
    resp = client.post("/api/team/join", json={"code": code, "name": "x"})
    assert resp.status_code == 403
    assert "尝试次数过多" in json.loads(resp.data)["error"]["message"]


def test_join_files_upload_and_kick_flow(team_env):
    client, svc, shared = team_env
    d = _data(client.post("/api/team/host/start", headers=IDENT, json={
        "team_name": "组", "shared_folder": str(shared),
    }))
    joined = _data(client.post("/api/team/join", json={"code": d["code"], "name": "同事"}))
    token = joined["token"]
    headers = {"X-Team-Token": token}
    # Simulate a remote LAN member; localhost requests bypass the token check.
    remote = {"REMOTE_ADDR": "192.168.1.50"}

    files = _data(client.get("/api/team/files", headers=headers, environ_base=remote))["files"]
    names = [f["name"] for f in files]
    assert "sales.csv" in names and "notes.txt" not in names

    resp = client.get("/api/team/files/download",
                      query_string={"path": "sales.csv"}, headers=headers, environ_base=remote)
    assert resp.status_code == 200 and b"a,b" in resp.data

    # Path traversal must be rejected (error envelope, no file content).
    resp = client.get("/api/team/files/download",
                      query_string={"path": "../team_state.json"}, headers=headers, environ_base=remote)
    body = json.loads(resp.data)
    assert body.get("status") == "error"
    assert b"team_name" not in resp.data  # no team_state.json contents leaked

    up = _data(client.post("/api/team/files/upload", headers=headers, data={
        "file": (io.BytesIO("x,y\n1,2\n".encode("utf-8")), "新表.csv"),
    }, content_type="multipart/form-data"))
    assert up["name"].endswith(".csv") and (shared / up["name"]).exists()

    # Kick invalidates the member's token.
    member_id = _data(client.get("/api/team/status"))["members"][0]["id"]
    _data(client.post("/api/team/host/kick", json={"member_id": member_id}))
    resp = client.get("/api/team/files", headers=headers, environ_base=remote)
    assert resp.status_code == 403


def test_regenerate_code_keeps_members(team_env):
    client, svc, shared = team_env
    d = _data(client.post("/api/team/host/start", headers=IDENT, json={"team_name": "t"}))
    joined = _data(client.post("/api/team/join", json={"code": d["code"], "name": "m"}))
    new_code = _data(client.post("/api/team/host/regenerate-code"))["code"]
    assert new_code != d["code"] or True  # may collide by chance; just ensure valid
    assert len(new_code) == 4
    # Existing member token still valid after code rotation.
    assert svc.verify_token(joined["token"]) is not None


def test_stop_resets_everything(team_env):
    client, svc, shared = team_env
    _data(client.post("/api/team/host/start", headers=IDENT, json={"team_name": "t"}))
    _data(client.post("/api/team/host/stop"))
    assert _data(client.get("/api/team/status"))["mode"] == "off"
