# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Server-side, per-identity store for user model configurations.

Motivation: model configs (including API keys) used to live only in the
browser's origin-keyed storage, so they were invisible across frontends
(web vs. desktop WebView) and were lost whenever the origin changed.
This store keeps the full config encrypted in the credential vault so
every frontend of the same identity sees the same models.

Security contract:
- everything is scoped to ``get_identity_id()`` — a user can only ever
  see or modify their own models;
- API keys go INTO the vault but are never returned by any endpoint;
  ``GET`` responses only carry a ``has_api_key`` flag. Agent calls whose
  config lacks a key are resolved server-side (see routes/agents.py).
"""
from __future__ import annotations

import logging

from flask import Blueprint, request

from data_formulator.auth.vault import get_credential_vault
from data_formulator.auth.identity import get_identity_id
from data_formulator.error_handler import json_ok
from data_formulator.errors import AppError, ErrorCode

logger = logging.getLogger(__name__)

user_models_bp = Blueprint("user_models", __name__, url_prefix="/api/user-models")

# Vault source_key namespace. Shares the per-identity keyspace with data
# connector credentials, hence the distinct prefix.
_MODEL_KEY_PREFIX = "llm:"
_SELECTED_KEY = "llm-selected-model"

_ALLOWED_FIELDS = ("id", "endpoint", "model", "api_key", "api_base", "api_version", "auth_mode")
_MAX_FIELD_LENGTH = 2048


def model_vault_key(model_id: str) -> str:
    return f"{_MODEL_KEY_PREFIX}{model_id}"


def _sanitize_model(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise AppError(ErrorCode.INVALID_REQUEST, "Invalid model configuration")
    entry = {f: str(value.get(f) or "").strip() for f in _ALLOWED_FIELDS}
    if not entry["id"] or not entry["endpoint"] or not entry["model"]:
        raise AppError(ErrorCode.INVALID_REQUEST, "id, endpoint and model are required")
    if any(len(v) > _MAX_FIELD_LENGTH for v in entry.values()):
        raise AppError(ErrorCode.INVALID_REQUEST, "Model configuration is too long")
    return entry


def _public_view(entry: dict) -> dict:
    """Strip the secret; report only whether one is stored."""
    return {
        "id": entry.get("id", ""),
        "endpoint": entry.get("endpoint", ""),
        "model": entry.get("model", ""),
        "api_base": entry.get("api_base", ""),
        "api_version": entry.get("api_version", ""),
        "auth_mode": entry.get("auth_mode", "") or None,
        "has_api_key": bool(entry.get("api_key")),
    }


@user_models_bp.route("", methods=["GET"])
def list_user_models():
    vault = get_credential_vault()
    if not vault:
        return json_ok({"available": False, "models": [], "selected_id": None})

    identity = get_identity_id()
    models = []
    for source_key in vault.list_sources(identity):
        if not source_key.startswith(_MODEL_KEY_PREFIX):
            continue
        entry = vault.retrieve(identity, source_key)
        if entry:
            models.append(_public_view(entry))

    selected = vault.retrieve(identity, _SELECTED_KEY) or {}
    return json_ok({
        "available": True,
        "models": models,
        "selected_id": selected.get("id") or None,
    })


@user_models_bp.route("", methods=["POST"])
def store_user_model():
    vault = get_credential_vault()
    if not vault:
        raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "Credential vault not configured")

    entry = _sanitize_model((request.get_json() or {}).get("model"))
    identity = get_identity_id()

    # Updating without re-typing the key keeps the previously stored secret.
    if not entry["api_key"]:
        existing = vault.retrieve(identity, model_vault_key(entry["id"])) or {}
        entry["api_key"] = existing.get("api_key", "")

    vault.store(identity, model_vault_key(entry["id"]), entry)
    logger.info("User model stored for %s / %s", identity[:16], entry["id"])
    return json_ok(_public_view(entry))


@user_models_bp.route("/delete", methods=["POST"])
def delete_user_model():
    vault = get_credential_vault()
    if not vault:
        raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "Credential vault not configured")

    model_id = str((request.get_json() or {}).get("id") or "").strip()
    if not model_id:
        raise AppError(ErrorCode.INVALID_REQUEST, "id required")

    identity = get_identity_id()
    vault.delete(identity, model_vault_key(model_id))
    selected = vault.retrieve(identity, _SELECTED_KEY) or {}
    if selected.get("id") == model_id:
        vault.delete(identity, _SELECTED_KEY)
    logger.info("User model deleted for %s / %s", identity[:16], model_id)
    return json_ok({"id": model_id})


@user_models_bp.route("/select", methods=["POST"])
def select_user_model():
    vault = get_credential_vault()
    if not vault:
        raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "Credential vault not configured")

    model_id = str((request.get_json() or {}).get("id") or "").strip()
    identity = get_identity_id()
    if model_id:
        vault.store(identity, _SELECTED_KEY, {"id": model_id})
    else:
        vault.delete(identity, _SELECTED_KEY)
    return json_ok({"id": model_id or None})
