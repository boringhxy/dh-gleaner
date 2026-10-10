"""MCP 工具的返回契约与失败分类。

所有工具都返回**扁平字典**，只有两种形状：

成功::

    {"ok": True, ...该工具自己的字段...}

失败::

    {"ok": False, "failureKind": "...", "message": "...", "suggestedAction": "..."}

`failureKind` 让 AI 客户端能判断「该换个 URL 重试、该请用户手动补、还是根本不该重试」，
而不是把一句报错原样丢给用户。分类的取值是稳定的机器可读枚举。
"""

from __future__ import annotations

from typing import Any

from ..http_util import FetchBlocked

# ---- failureKind 取值 -------------------------------------------------------
KIND_NETWORK = "network"                    # 网络不通 / 超时 / 重试耗尽
KIND_BLOCKED = "blocked"                    # 站点拒绝访问（401/403/412），重试无意义
KIND_CAPTCHA = "captcha"                    # 需要验证码或登录
KIND_EMPTY = "empty_parse"                  # 能访问但解析不出文章
KIND_ISSUE_MISMATCH = "issue_mismatch"      # 抓到的期次与目标不符，疑似误抓
KIND_NOT_CONFIGURED = "not_configured"      # 缺少 Zotero 凭据等前置配置
KIND_INVALID_INPUT = "invalid_input"        # 参数不合法
KIND_NO_PENDING = "no_pending"              # 没有待筛/待导入数据
KIND_UNKNOWN = "unknown"

_SUGGESTIONS = {
    KIND_NETWORK: "稍后重试；若持续失败，可用 url 参数直接指定目录页地址。",
    KIND_BLOCKED: "站点拒绝自动化访问，重试无用。请换用该期次的单期目录页地址（url 参数），或改用手工补录。",
    KIND_CAPTCHA: "该页需要验证码或登录，工具不会绕过。请用 url 参数指定一个公开可访问的目录页，或手工补录目录。",
    KIND_EMPTY: "页面能打开但没有解析出文章。请用 url 参数确认目录页正确，或检查该期次是否尚未上线。",
    KIND_ISSUE_MISMATCH: "抓到内容与目标期次不符，旧清单未被覆盖。请核对 year/issue，或直接用 url 指定该期目录页。",
    KIND_NOT_CONFIGURED: "请先配置你自己的 Zotero 凭据（见 run_doctor 输出的配置路径），再重试。",
    KIND_INVALID_INPUT: "请修正参数后重试。",
    KIND_NO_PENDING: "请先用 capture_issue 或 capture_channel 抓取目录，再执行本操作。",
    KIND_UNKNOWN: "请查看 message 与 run_doctor 的输出定位问题。",
}


def classifyFailure(message: str = "", error: object = None) -> str:
    """把一段错误信息/异常归类成 failureKind。"""
    if isinstance(error, FetchBlocked):
        return KIND_BLOCKED

    text = f"{message} {error or ''}"
    if "412" in text or "403" in text or "拒绝访问" in text:
        return KIND_BLOCKED
    if "验证码" in text or "需登录" in text or "未登录" in text:
        return KIND_CAPTCHA
    if "未配置" in text or "credential" in text.lower():
        return KIND_NOT_CONFIGURED
    if "疑似误抓" in text or "0 年第 0 期" in text:
        return KIND_ISSUE_MISMATCH
    networkMarkers = ("timeout", "timed out", "Connection", "Max retries", "SSLError", "NameResolution", "抓取失败")
    if any(marker in text for marker in networkMarkers):
        return KIND_NETWORK
    return KIND_UNKNOWN


def suggestedAction(kind: str) -> str:
    return _SUGGESTIONS.get(kind, _SUGGESTIONS[KIND_UNKNOWN])


def failure(message: str, kind: str | None = None, error: object = None, **extra: Any) -> dict:
    """构造失败返回。"""
    resolved = kind or classifyFailure(message, error)
    payload: dict[str, Any] = {
        "ok": False,
        "failureKind": resolved,
        "message": message,
        "suggestedAction": suggestedAction(resolved),
    }
    payload.update(extra)
    return payload


def success(**payload: Any) -> dict:
    """构造成功返回。"""
    return {"ok": True, **payload}
