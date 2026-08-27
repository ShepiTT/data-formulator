# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""LAN team collaboration routes (协作码).

Surface overview
----------------
Local-only management (the app owner's own browser):
    POST /api/team/host/start        create a team, get the 4-digit code
    POST /api/team/host/stop         stop hosting
    POST /api/team/host/regenerate-code
    POST /api/team/host/kick         {member_id}
    POST /api/team/host/settings     {shared_folder?, shared_model_ids?}
    GET  /api/team/status
    POST /api/team/join-team         guest: discover by code + join + install
    POST /api/team/leave             guest: leave and clean up
    POST /api/team/upload-file       guest: push a local file to the team share

Remote, member-token protected (what teammates' backends call on the host):
    POST /api/team/join              {code, name} -> {token}
    GET  /api/team/files
    GET  /api/team/files/download?path=...
    POST /api/team/files/upload
    GET  /api/team/models
    POST /api/team/v1/chat/completions   OpenAI-compatible relay; the host's
                                         API keys never leave the host.

Chats and sessions are never shared: members keep using their own local
backend for everything except the endpoints above.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from flask import Blueprint, Response, request, send_file

from data_formulator.error_handler import json_ok
from data_formulator.errors import AppError, ErrorCode
from data_formulator.team.service import team_service, discover_host
from data_formulator.security.path_safety import ConfinedDir

logger = logging.getLogger(__name__)

team_bp = Blueprint("team", __name__, url_prefix="/api/team")

_SHAREABLE_EXTENSIONS = frozenset({
    ".csv", ".tsv", ".parquet", ".json", ".jsonl", ".xlsx", ".xls",
})
_MAX_UPLOAD_BYTES = 200 * 1024 * 1024

# Prefix used for virtual models installed on a member's machine; also used
# on leave to find and remove them.
TEAM_MODEL_PREFIX = "team-"


# -- access helpers ---------------------------------------------------------

def _is_local_request() -> bool:
    return (request.remote_addr or "") in ("127.0.0.1", "::1")


def _require_local() -> None:
    if not _is_local_request():
        raise AppError(ErrorCode.ACCESS_DENIED, "This endpoint is local-only")


def _require_member() -> dict:
    token = None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[len("Bearer "):].strip()
    token = token or request.headers.get("X-Team-Token")
    member = team_service.verify_token(token)
    if not member:
        raise AppError(ErrorCode.ACCESS_DENIED, "Invalid or expired team token")
    return member


def _shared_jail() -> ConfinedDir:
    folder = team_service.raw().get("shared_folder") or ""
    if not folder or not os.path.isdir(folder):
        raise AppError(ErrorCode.INVALID_REQUEST, "No shared folder configured")
    return ConfinedDir(Path(folder), mkdir=False)


# -- host management (local-only) ------------------------------------------

@team_bp.route("/host/start", methods=["POST"])
def host_start():
    _require_local()
    from data_formulator.auth.identity import get_identity_id

    data = request.get_json() or {}
    team_name = str(data.get("team_name") or "").strip() or "我的团队"
    shared_folder = str(data.get("shared_folder") or "").strip()
    if shared_folder:
        expanded = os.path.expandvars(os.path.expanduser(shared_folder))
        if not os.path.isdir(expanded):
            raise AppError(ErrorCode.INVALID_REQUEST, f"文件夹不存在: {expanded}")
        shared_folder = expanded

    try:
        http_port = int(request.host.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        http_port = 80

    status = team_service.start_hosting(
        team_name=team_name,
        host_identity=get_identity_id(),
        http_port=http_port,
        shared_folder=shared_folder,
    )
    return json_ok(status)


@team_bp.route("/host/stop", methods=["POST"])
def host_stop():
    _require_local()
    team_service.stop()
    return json_ok({"mode": "off"})


@team_bp.route("/host/regenerate-code", methods=["POST"])
def host_regenerate_code():
    _require_local()
    try:
        return json_ok({"code": team_service.regenerate_code()})
    except ValueError:
        raise AppError(ErrorCode.INVALID_REQUEST, "Not hosting a team")


@team_bp.route("/host/kick", methods=["POST"])
def host_kick():
    _require_local()
    member_id = str((request.get_json() or {}).get("member_id") or "")
    if not member_id:
        raise AppError(ErrorCode.INVALID_REQUEST, "member_id required")
    team_service.kick_member(member_id)
    return json_ok(team_service.status())


@team_bp.route("/host/settings", methods=["POST"])
def host_settings():
    _require_local()
    data = request.get_json() or {}
    shared_folder = data.get("shared_folder")
    if shared_folder is not None:
        shared_folder = os.path.expandvars(os.path.expanduser(str(shared_folder).strip()))
        if shared_folder and not os.path.isdir(shared_folder):
            raise AppError(ErrorCode.INVALID_REQUEST, f"文件夹不存在: {shared_folder}")
    shared_model_ids = data.get("shared_model_ids")
    if shared_model_ids is not None and not isinstance(shared_model_ids, list):
        raise AppError(ErrorCode.INVALID_REQUEST, "shared_model_ids must be a list")
    try:
        team_service.update_host_settings(shared_folder, shared_model_ids)
    except ValueError:
        raise AppError(ErrorCode.INVALID_REQUEST, "Not hosting a team")
    return json_ok(team_service.status())


@team_bp.route("/status", methods=["GET"])
def status():
    _require_local()
    return json_ok(team_service.status())


# -- join / member endpoints (reachable from the LAN) -----------------------

@team_bp.route("/join", methods=["POST"])
def join():
    data = request.get_json() or {}
    code = str(data.get("code") or "").strip()
    name = str(data.get("name") or "").strip()
    if not re.fullmatch(r"\d{4}", code):
        raise AppError(ErrorCode.INVALID_REQUEST, "code must be 4 digits")
    try:
        result = team_service.try_join(code, name, request.remote_addr or "?")
    except PermissionError:
        raise AppError(ErrorCode.ACCESS_DENIED, "尝试次数过多，请一分钟后再试")
    if result is None:
        raise AppError(ErrorCode.ACCESS_DENIED, "协作码不正确")
    logger.info("Team member joined: %s (%s)", result["name"], request.remote_addr)
    return json_ok(result)


@team_bp.route("/files", methods=["GET"])
def list_files():
    if not _is_local_request():
        _require_member()
    jail = _shared_jail()
    root = jail.root if hasattr(jail, "root") else Path(team_service.raw()["shared_folder"])
    files = []
    for p in sorted(Path(team_service.raw()["shared_folder"]).rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in _SHAREABLE_EXTENSIONS:
            continue
        rel = p.relative_to(Path(team_service.raw()["shared_folder"]))
        try:
            stat = p.stat()
        except OSError:
            continue
        files.append({
            "path": str(rel).replace("\\", "/"),
            "name": p.name,
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "file_type": p.suffix.lstrip(".").lower(),
        })
    return json_ok({"files": files})


@team_bp.route("/files/download", methods=["GET"])
def download_file():
    if not _is_local_request():
        _require_member()
    jail = _shared_jail()
    rel = request.args.get("path", "")
    try:
        resolved = jail / rel
    except ValueError:
        raise AppError(ErrorCode.INVALID_REQUEST, "Invalid path")
    if not resolved.is_file() or resolved.suffix.lower() not in _SHAREABLE_EXTENSIONS:
        raise AppError(ErrorCode.NOT_FOUND, "File not found")
    return send_file(str(resolved), as_attachment=True, download_name=resolved.name)


@team_bp.route("/files/upload", methods=["POST"])
def upload_file():
    if not _is_local_request():
        _require_member()
    jail = _shared_jail()
    file = request.files.get("file")
    if file is None or not file.filename:
        raise AppError(ErrorCode.INVALID_REQUEST, "file required")
    # Keep CJK characters; strip path separators and control chars.
    base = os.path.basename(file.filename)
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", base).strip() or "upload"
    if Path(base).suffix.lower() not in _SHAREABLE_EXTENSIONS:
        raise AppError(ErrorCode.INVALID_REQUEST, "仅支持数据文件（csv/tsv/xlsx/json/parquet）")
    target = jail / base
    stem, ext = os.path.splitext(base)
    counter = 1
    while target.exists():
        target = jail / f"{stem} ({counter}){ext}"
        counter += 1
    file.save(str(target))
    if target.stat().st_size > _MAX_UPLOAD_BYTES:
        target.unlink(missing_ok=True)
        raise AppError(ErrorCode.INVALID_REQUEST, "文件过大（上限 200MB）")
    logger.info("Team file uploaded: %s", target.name)
    return json_ok({"name": target.name})


@team_bp.route("/models", methods=["GET"])
def list_models():
    if not _is_local_request():
        _require_member()
    raw = team_service.raw()
    shared_ids = raw.get("shared_model_ids", [])
    host_identity = raw.get("host_identity")
    if not shared_ids or not host_identity:
        return json_ok({"models": []})

    from data_formulator.auth.vault import get_credential_vault
    from data_formulator.routes.user_models import model_vault_key

    vault = get_credential_vault()
    models = []
    if vault:
        for mid in shared_ids:
            cfg = vault.retrieve(host_identity, model_vault_key(mid))
            if cfg:
                models.append({
                    "id": mid,
                    "endpoint": cfg.get("endpoint", ""),
                    "model": cfg.get("model", ""),
                })
    return json_ok({"models": models})


# -- OpenAI-compatible LLM relay (member token; keys stay on the host) ------

_RELAY_PASSTHROUGH = (
    "messages", "tools", "tool_choice", "stream", "temperature", "top_p",
    "max_tokens", "max_completion_tokens", "reasoning_effort",
    "response_format", "stop",
)


@team_bp.route("/v1/chat/completions", methods=["POST"])
def llm_relay():
    if not _is_local_request():
        member = _require_member()
    else:
        member = {"name": "host"}
    body = request.get_json() or {}
    model_id = str(body.get("model") or "")

    raw = team_service.raw()
    shared_ids = raw.get("shared_model_ids", [])

    from data_formulator.auth.vault import get_credential_vault
    from data_formulator.routes.user_models import model_vault_key
    from data_formulator.agents.client_utils import Client

    vault = get_credential_vault()
    # Accept either a shared model's id or its underlying model name — members'
    # virtual configs carry the readable model name for display.
    cfg = None
    if vault:
        if model_id in shared_ids:
            cfg = vault.retrieve(raw["host_identity"], model_vault_key(model_id))
        else:
            for mid in shared_ids:
                candidate = vault.retrieve(raw["host_identity"], model_vault_key(mid))
                if candidate and candidate.get("model") == model_id:
                    cfg = candidate
                    break
    if not cfg:
        raise AppError(ErrorCode.ACCESS_DENIED, "该模型未共享给团队")

    client = Client(
        cfg.get("endpoint", "openai"), cfg.get("model", ""),
        cfg.get("api_key") or None, cfg.get("api_base") or None,
        cfg.get("api_version") or None,
    )

    import litellm

    params = {k: body[k] for k in _RELAY_PASSTHROUGH if k in body}
    stream = bool(params.pop("stream", False))
    logger.info("Team LLM relay: %s -> %s (%s)", member.get("name"), model_id, cfg.get("model"))

    try:
        resp = litellm.completion(
            model=client.model, drop_params=True, _skip_mcp_handler=True,
            stream=stream, **client.params, **params,
        )
    except Exception as exc:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"模型调用失败: {exc}") from exc

    if not stream:
        return Response(json.dumps(resp.model_dump()), mimetype="application/json")

    def generate():
        try:
            for chunk in resp:
                yield f"data: {json.dumps(chunk.model_dump())}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return Response(generate(), mimetype="text/event-stream")


# -- guest-side management (local-only) -------------------------------------

def _team_base_url() -> str:
    st = team_service.raw()
    return st.get("host_url", "")


@team_bp.route("/join-team", methods=["POST"])
def join_team():
    """Discover the host by code, join, and install shared resources locally."""
    _require_local()
    import requests as http

    data = request.get_json() or {}
    code = str(data.get("code") or "").strip()
    if not re.fullmatch(r"\d{4}", code):
        raise AppError(ErrorCode.INVALID_REQUEST, "请输入 4 位协作码")
    member_name = str(data.get("name") or "").strip() or os.environ.get("USERNAME") or "member"

    found = discover_host(code)
    if not found:
        raise AppError(
            ErrorCode.NOT_FOUND,
            "在局域网内没有找到这个协作码对应的团队。请确认对方已开启团队协作、双方在同一网络。",
        )
    host_url = f"http://{found['ip']}:{found['port']}"

    resp = http.post(f"{host_url}/api/team/join",
                     json={"code": code, "name": member_name}, timeout=8)
    payload = resp.json()
    if resp.status_code != 200 or payload.get("status") != "success":
        detail = (payload.get("error") or {}).get("message", "加入失败")
        raise AppError(ErrorCode.ACCESS_DENIED, detail)
    joined = payload["data"]
    token = joined["token"]
    team_name = joined.get("team_name") or found.get("team_name") or "团队"

    team_service.set_membership(host_url, team_name, token, member_name)

    installed_models = _install_team_models(host_url, token)
    connector_ok = _register_team_connector(host_url, token, team_name)

    return json_ok({
        "team_name": team_name,
        "host_url": host_url,
        "installed_models": installed_models,
        "connector_registered": connector_ok,
    })


@team_bp.route("/leave", methods=["POST"])
def leave_team():
    _require_local()
    _remove_team_models()
    _remove_team_connector()
    team_service.stop()
    return json_ok({"mode": "off"})


@team_bp.route("/upload-file", methods=["POST"])
def member_upload_file():
    """Member UI helper: push a local file up to the host's shared folder."""
    _require_local()
    st = team_service.raw()
    if st.get("mode") != "member":
        raise AppError(ErrorCode.INVALID_REQUEST, "未加入团队")
    file = request.files.get("file")
    if file is None:
        raise AppError(ErrorCode.INVALID_REQUEST, "file required")
    import requests as http
    resp = http.post(
        f"{st['host_url']}/api/team/files/upload",
        headers={"X-Team-Token": st["member_token"]},
        files={"file": (file.filename, file.stream, file.mimetype)},
        timeout=120,
    )
    payload = resp.json()
    if resp.status_code != 200 or payload.get("status") != "success":
        detail = (payload.get("error") or {}).get("message", "上传失败")
        raise AppError(ErrorCode.INTERNAL_ERROR, detail)
    return json_ok(payload["data"])


# -- guest-side installation helpers ---------------------------------------

def _install_team_models(host_url: str, token: str) -> list[str]:
    """Store the host's shared models as local virtual models: OpenAI-compatible
    configs whose api_base is the host relay and whose api_key is the member
    token. The host's real keys never reach this machine."""
    import requests as http
    from data_formulator.auth.vault import get_credential_vault
    from data_formulator.auth.identity import get_identity_id
    from data_formulator.routes.user_models import model_vault_key

    vault = get_credential_vault()
    if not vault:
        return []
    try:
        resp = http.get(f"{host_url}/api/team/models",
                        headers={"X-Team-Token": token}, timeout=8)
        shared = (resp.json().get("data") or {}).get("models", [])
    except Exception:
        logger.warning("Failed to fetch team models", exc_info=True)
        return []

    identity = get_identity_id()
    installed = []
    for m in shared:
        vid = f"{TEAM_MODEL_PREFIX}{m['id']}"
        entry = {
            "id": vid,
            "endpoint": "openai",
            "model": m.get("model") or m["id"],
            "api_key": token,
            "api_base": f"{host_url}/api/team/v1",
            "api_version": "",
            "auth_mode": "",
        }
        vault.store(identity, model_vault_key(vid), entry)
        installed.append(f"{m.get('model', m['id'])}（团队共享）")
    return installed


def _remove_team_models() -> None:
    from data_formulator.auth.vault import get_credential_vault
    from data_formulator.auth.identity import get_identity_id
    from data_formulator.routes.user_models import model_vault_key, _MODEL_KEY_PREFIX

    vault = get_credential_vault()
    if not vault:
        return
    identity = get_identity_id()
    for source_key in vault.list_sources(identity):
        if source_key.startswith(f"{_MODEL_KEY_PREFIX}{TEAM_MODEL_PREFIX}"):
            vault.delete(identity, source_key)


_TEAM_CONNECTOR_ID = "team_share"


def _register_team_connector(host_url: str, token: str, team_name: str) -> bool:
    try:
        from data_formulator.data_loader import DATA_LOADERS
        from data_formulator.data_connector import (
            DATA_CONNECTORS, DataConnector, SourceSpec,
            _persist_user_connector, _user_connector_key,
        )
        from data_formulator.auth.identity import get_identity_id

        loader_class = DATA_LOADERS.get("team_share")
        if not loader_class:
            return False
        identity = get_identity_id()
        params = {"host_url": host_url, "token": token}
        connector = DataConnector.from_loader(
            loader_class,
            source_id=_TEAM_CONNECTOR_ID,
            display_name=f"团队共享 · {team_name}",
            default_params=params,
            icon="local_folder",
        )
        DATA_CONNECTORS[_user_connector_key(identity, _TEAM_CONNECTOR_ID)] = connector
        _persist_user_connector(identity, SourceSpec(
            source_id=_TEAM_CONNECTOR_ID,
            loader_type="team_share",
            display_name=f"团队共享 · {team_name}",
            default_params=params,
            icon="local_folder",
            source="user",
        ))
        connector._connect(params)
        return True
    except Exception:
        logger.warning("Failed to register team connector", exc_info=True)
        return False


def _remove_team_connector() -> None:
    try:
        from data_formulator.data_connector import (
            DATA_CONNECTORS, _remove_user_connector, _user_connector_key,
        )
        from data_formulator.auth.identity import get_identity_id

        identity = get_identity_id()
        DATA_CONNECTORS.pop(_user_connector_key(identity, _TEAM_CONNECTOR_ID), None)
        _remove_user_connector(identity, _TEAM_CONNECTOR_ID)
    except Exception:
        logger.debug("Team connector cleanup failed", exc_info=True)
