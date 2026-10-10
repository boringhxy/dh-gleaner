"""配置加载 —— 包内默认配置 + 数据目录覆盖 + 环境变量优先。

合并顺序（后者覆盖前者）：

1. 包内 `dhjournal/defaults/config.json`（只读，密钥字段为空串）
2. `<数据目录>/config.json`
3. `<数据目录>/config.local.json`（用户在模板基础上粘贴自己的 Zotero 凭据）
4. 环境变量 `ZOTERO_LIBRARY_ID` / `ZOTERO_WEB_LIBRARY_ID`、
   `ZOTERO_API_KEY` / `ZOTERO_WEB_API_KEY`（最高优先）

Zotero 凭据始终是**使用者自己的**：本工具只读取，不生成、不上传、不代为保管。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Sequence

from .paths import (
    ENV_API_KEY,
    ENV_LIBRARY_ID,
    PLACEHOLDER_VALUES,
    defaultConfigPath,
    getPaths,
)


def _deepMerge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deepMerge(base[key], value)
        else:
            base[key] = value
    return base


def _readJson(path: Path, optional: bool = True) -> dict:
    if not path.is_file():
        if optional:
            return {}
        raise FileNotFoundError(f"配置文件不存在: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"配置文件不是合法 JSON: {path}（{e}）") from e
    return data if isinstance(data, dict) else {}


def _firstEnv(names: Sequence[str]) -> str:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return ""


def normalizeCredentials(cfg: dict) -> dict:
    """把占位符或空白凭据归一成空串，避免「看起来配了其实没配」。"""
    zotero = cfg.setdefault("zotero", {})
    for field in ("webLibraryId", "webApiKey"):
        value = str(zotero.get(field) or "").strip()
        zotero[field] = "" if value in PLACEHOLDER_VALUES else value
    return cfg


def applyEnvOverrides(cfg: dict) -> dict:
    zotero = cfg.setdefault("zotero", {})
    envLibraryId = _firstEnv(ENV_LIBRARY_ID)
    envApiKey = _firstEnv(ENV_API_KEY)
    if envLibraryId:
        zotero["webLibraryId"] = envLibraryId
    if envApiKey:
        zotero["webApiKey"] = envApiKey
    return cfg


def loadConfig() -> dict:
    """加载并合并配置，返回可直接使用的 dict。"""
    paths = getPaths()
    cfg = _readJson(defaultConfigPath())
    _deepMerge(cfg, _readJson(paths.configPath))
    _deepMerge(cfg, _readJson(paths.configLocalPath))
    applyEnvOverrides(cfg)
    normalizeCredentials(cfg)
    return cfg


def zoteroCredentials(cfg: dict) -> tuple[str, str]:
    """返回 (libraryId, apiKey)，占位符视为未配置。"""
    zotero = cfg.get("zotero") or {}
    libraryId = str(zotero.get("webLibraryId") or "").strip()
    apiKey = str(zotero.get("webApiKey") or "").strip()
    if libraryId in PLACEHOLDER_VALUES:
        libraryId = ""
    if apiKey in PLACEHOLDER_VALUES:
        apiKey = ""
    return libraryId, apiKey


def isZoteroConfigured(cfg: dict) -> tuple[bool, str]:
    """判断 Zotero 凭据是否可用；未配置时返回缺失的字段名。"""
    libraryId, apiKey = zoteroCredentials(cfg)
    missing = []
    if not libraryId:
        missing.append("webLibraryId")
    if not apiKey:
        missing.append("webApiKey")
    if not missing:
        return True, ""
    return False, "、".join(missing)


def credentialHint() -> str:
    """未配置凭据时给用户的操作指引（文案里不出现「申请 / 领取」字样）。"""
    paths = getPaths()
    return (
        "运行 `dhjournal init` 可交互式录入凭据并测试连接；"
        f"或把密钥模板复制为 {paths.configLocalPath}，"
        "粘贴你自己的 Zotero library ID 与 API key 后保存"
        "（`dhjournal doctor` 可查看期望路径与模板路径）。"
    )
