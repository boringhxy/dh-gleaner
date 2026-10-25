"""数据目录解析 —— 让工具在 pip 安装后仍有可写的运行目录。

解析优先级（`resolveDataDir`）：

1. `--data-dir` 命令行参数（单次生效）
2. `DHGLEANER_DATA_DIR` 环境变量（永久生效）
3. 遗留探测：当前目录有本工具源码，或可识别的配置/运行数据
4. 兜底 `~/.dhgleaner`

本模块**只读探测**，不迁移、不删除任何现有文件；所有产物路径都以数据目录为根，
沿用 `data/`、`logs/`、`tmp/` 的既有布局，因此遗留模式下的落盘位置与改造前逐字节一致。
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterator, Optional, Union

ENV_DATA_DIR = "DHGLEANER_DATA_DIR"
DEFAULT_DIR_NAME = ".dhgleaner"

ENV_LIBRARY_ID = ("ZOTERO_LIBRARY_ID", "ZOTERO_WEB_LIBRARY_ID")
ENV_API_KEY = ("ZOTERO_API_KEY", "ZOTERO_WEB_API_KEY")

SOURCE_CLI = "cli"
SOURCE_ENV = "env"
SOURCE_LEGACY = "legacy"
SOURCE_DEFAULT = "default"

# 密钥模板里的占位符：出现这些值一律视为「未配置」，避免非空字符串被误判为已配置。
PLACEHOLDER_VALUES = frozenset(
    {
        "",
        "你的用户ID",
        "你的API Key",
        "your-user-id",
        "your_user_id",
        "your-api-key",
        "your_api_key",
        "YOUR_USER_ID",
        "YOUR_API_KEY",
    }
)

PathLike = Union[str, Path]


@dataclass(frozen=True)
class Paths:
    """一个数据目录下的全部固定产物路径。"""

    dataDir: Path
    source: str

    @property
    def configPath(self) -> Path:
        return self.dataDir / "config.json"

    @property
    def configLocalPath(self) -> Path:
        return self.dataDir / "config.local.json"

    @property
    def dataSubdir(self) -> Path:
        return self.dataDir / "data"

    @property
    def pending(self) -> Path:
        return self.dataSubdir / "pending.json"

    @property
    def review(self) -> Path:
        return self.dataSubdir / "review.md"

    @property
    def captureStatus(self) -> Path:
        return self.dataSubdir / "last_capture_status.json"

    @property
    def importReport(self) -> Path:
        return self.dataSubdir / "import_report.md"

    @property
    def titleMatchReport(self) -> Path:
        return self.dataSubdir / "title_match_report.md"

    @property
    def selection(self) -> Path:
        return self.dataSubdir / "selection.json"

    @property
    def spreadsheet(self) -> Path:
        return self.dataSubdir / "review_selection.xlsx"

    @property
    def backupDir(self) -> Path:
        return self.dataSubdir / "backups"

    @property
    def defaultStateFile(self) -> Path:
        return self.dataSubdir / "state.json"

    @property
    def defaultLogFile(self) -> Path:
        return self.dataDir / "logs" / "capture.log"

    @property
    def defaultTempDir(self) -> Path:
        return self.dataDir / "tmp"

    def describeSource(self) -> str:
        labels = {
            SOURCE_CLI: "cli",
            SOURCE_ENV: "env",
            SOURCE_LEGACY: "legacy",
            SOURCE_DEFAULT: "default",
        }
        return labels.get(self.source, self.source)


def resolveDataDir(cliDir: Optional[PathLike] = None) -> tuple[Path, str]:
    """按优先级解析数据目录，返回 (目录, 来源标签)。不创建任何目录。"""
    if cliDir:
        return Path(cliDir).expanduser().resolve(), SOURCE_CLI

    envValue = os.getenv(ENV_DATA_DIR)
    if envValue and envValue.strip():
        return Path(envValue.strip()).expanduser().resolve(), SOURCE_ENV

    cwd = Path.cwd()
    if _isLegacyDataRoot(cwd):
        return cwd.resolve(), SOURCE_LEGACY

    return (Path.home() / DEFAULT_DIR_NAME), SOURCE_DEFAULT


def _isLegacyDataRoot(directory: Path) -> bool:
    if (directory / "dhgleaner" / "paths.py").is_file() and (directory / "pyproject.toml").is_file():
        return True
    for name in ("config.json", "data/state.json", "data/pending.json"):
        try:
            data = json.loads((directory / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if name == "config.json" and isinstance(data.get("journals"), list) and isinstance(data.get("zotero"), dict):
            return True
        if name == "data/state.json" and isinstance(data.get("journals"), dict):
            return True
        if name == "data/pending.json" and isinstance(data.get("articles"), list) and "capturedAt" in data and "markdown" in data:
            return True
    return False


_cached: Optional[Paths] = None


def getPaths() -> Paths:
    """取当前数据目录的路径集合（进程内缓存）。"""
    global _cached
    if _cached is None:
        directory, source = resolveDataDir()
        _cached = Paths(dataDir=directory, source=source)
    return _cached


def setDataDir(value: Optional[PathLike] = None) -> Paths:
    """显式设定数据目录并刷新缓存；传 None 则重新按优先级解析。"""
    global _cached
    directory, source = resolveDataDir(value) if value else resolveDataDir()
    _cached = Paths(dataDir=directory, source=source)
    return _cached


def resetPaths() -> None:
    """清空缓存（测试用）。"""
    global _cached
    _cached = None


@contextlib.contextmanager
def useDataDir(value: PathLike) -> Iterator[Paths]:
    """在 `with` 块内把数据目录临时指向 `value`，退出时精确还原原缓存。"""
    global _cached
    previous = _cached
    _cached = Paths(dataDir=Path(value).expanduser().resolve(), source=SOURCE_CLI)
    try:
        yield _cached
    finally:
        _cached = previous


def resolveRuntimePath(value: Optional[str], fallback: Path) -> Path:
    """把配置里的相对路径按数据目录展开，绝对路径原样返回。"""
    if not value:
        return fallback
    path = Path(value).expanduser()
    return path if path.is_absolute() else getPaths().dataDir / path


def _packageData(name: str) -> Path:
    try:
        return Path(str(resources.files("dhgleaner") / "defaults" / name))
    except Exception:  # 未安装且无法定位包时回退到源码目录
        return Path(__file__).resolve().parent / "defaults" / name


def defaultConfigPath() -> Path:
    """包内默认配置（只读，密钥字段为空串）。"""
    return _packageData("config.json")


def configTemplatePath() -> Path:
    """包内密钥模板：用户复制为 <数据目录>/config.local.json 后粘贴自己的值。"""
    return _packageData("config.local.example.json")
