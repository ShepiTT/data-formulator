# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Team share data loader — browses the team host's shared folder over HTTP.

Registered automatically on a member's machine when they join a team
(see routes/team.py); it is not offered in the "add connector" catalog.
Files are fetched from the host on demand into a local temp cache and then
parsed exactly like local files.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq

from data_formulator.data_loader.external_data_loader import (
    ExternalDataLoader, CatalogNode, MAX_IMPORT_ROWS,
)
from data_formulator.data_loader import probe_utils
from data_formulator.datalake.parquet_utils import df_to_safe_records

logger = logging.getLogger(__name__)


class TeamShareDataLoader(ExternalDataLoader):
    """Read data files from the team host's shared folder."""

    DISPLAY_NAME = "团队共享文件"

    @staticmethod
    def list_params() -> list[dict[str, Any]]:
        return [
            {
                "name": "host_url",
                "type": "string",
                "required": True,
                "default": "",
                "tier": "connection",
                "description": "Team host base URL (set automatically on join)",
            },
            {
                "name": "token",
                "type": "string",
                "required": True,
                "default": "",
                "tier": "auth",
                "description": "Team member token (set automatically on join)",
            },
        ]

    AUTH_GUIDE = "team_share.md"

    @staticmethod
    def catalog_hierarchy() -> list[dict[str, str]]:
        return [{"key": "table", "label": "File"}]

    def __init__(self, params: dict[str, Any]):
        self.params = params
        self.host_url = (params.get("host_url") or "").rstrip("/")
        self.token = params.get("token") or ""

    # -- HTTP helpers ------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"X-Team-Token": self.token}

    def _list_remote(self) -> list[dict[str, Any]]:
        import requests
        resp = requests.get(
            f"{self.host_url}/api/team/files", headers=self._headers(), timeout=10,
        )
        resp.raise_for_status()
        return (resp.json().get("data") or {}).get("files", [])

    def _fetch_remote(self, rel_path: str) -> Path:
        """Download one shared file into the local temp cache; returns its path."""
        import requests
        cache_dir = Path(tempfile.gettempdir()) / "df_team_share"
        cache_dir.mkdir(parents=True, exist_ok=True)
        safe_name = rel_path.replace("/", "__").replace("\\", "__")
        target = cache_dir / safe_name
        resp = requests.get(
            f"{self.host_url}/api/team/files/download",
            params={"path": rel_path}, headers=self._headers(),
            timeout=120, stream=True,
        )
        resp.raise_for_status()
        with open(target, "wb") as f:
            for chunk in resp.iter_content(1 << 20):
                f.write(chunk)
        return target

    # -- loader interface --------------------------------------------------

    def test_connection(self) -> bool:
        try:
            self._list_remote()
            return True
        except Exception:
            return False

    def ls(self, path: list[str] | None = None,
           filter: str | None = None) -> list[CatalogNode]:
        if path:
            return []
        nodes = []
        for f in self._list_remote():
            if filter and filter.lower() not in f["path"].lower():
                continue
            nodes.append(CatalogNode(
                name=f["path"],
                node_type="table",
                path=[f["path"]],
                metadata={
                    "file_size": f.get("size"),
                    "modified": f.get("modified"),
                    "file_type": f.get("file_type"),
                    "row_count": None,
                },
            ))
        return nodes

    def get_metadata(self, path: list[str]) -> dict[str, Any]:
        if not path:
            return {}
        meta: dict[str, Any] = {}
        try:
            table = self.fetch_data_as_arrow(path[0], {"size": 5})
            sample_df = table.to_pandas()
            meta["columns"] = [
                {"name": c, "type": str(sample_df[c].dtype)}
                for c in sample_df.columns
            ]
            meta["sample_rows"] = df_to_safe_records(sample_df)
        except Exception as exc:
            logger.debug("Team share sample read failed for %s: %s", path, exc)
        return meta

    def list_tables(self, table_filter: str | None = None) -> list[dict[str, Any]]:
        results = []
        for f in self._list_remote():
            if table_filter and table_filter.lower() not in f["path"].lower():
                continue
            results.append({
                "name": f["path"],
                "metadata": {
                    "file_size": f.get("size"),
                    "modified": f.get("modified"),
                    "file_type": f.get("file_type"),
                },
                "path": [f["path"]],
            })
        return results

    def fetch_data_as_arrow(
        self,
        source_table: str,
        import_options: dict[str, Any] | None = None,
    ) -> pa.Table:
        local = self._fetch_remote(source_table)
        opts = import_options or {}
        size = opts.get("size", 1_000_000)

        ext = os.path.splitext(source_table)[1].lower()
        if ext == ".parquet":
            table = pq.read_table(str(local))
        elif ext in (".csv", ".tsv"):
            parse_options = (
                pa_csv.ParseOptions(delimiter="\t") if ext == ".tsv" else None
            )
            table = pa_csv.read_csv(str(local), parse_options=parse_options)
        elif ext in (".json", ".jsonl"):
            import pyarrow.json as pa_json
            table = pa_json.read_json(str(local))
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(str(local))
            table = pa.Table.from_pandas(df)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        self._last_total_rows = table.num_rows
        if table.num_rows > size:
            table = table.slice(0, size)
        logger.info("Fetched %d rows from team share: %s", table.num_rows, source_table)
        return table

    def probe(self, path: list[str], query: dict[str, Any]) -> dict[str, Any]:
        return probe_utils.run_probe_on_duckdb(self, path, query, scan_size=MAX_IMPORT_ROWS)
