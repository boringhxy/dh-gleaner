"""HTTP 请求工具 — 带 UA、分级重试、编码处理。

重试策略按状态码分级，避免在「对方明确拒绝自动化访问」时空等：

- ``401/403/412``：站点拒绝访问（412 常见于中文期刊站点的反爬前置检查），
  重试不会变好，**立刻放弃并抛出 `FetchBlocked`**，让上层换 URL 或转人工。
- ``408/425/429/5xx``：临时性故障，按 `retryInterval` 指数退避重试；站点若给了
  ``Retry-After`` 就听站点的。
- 其他异常（连接超时、DNS 失败等）：照旧重试。

抛出的异常都继承 `RuntimeError`，与改造前的调用方兼容。
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

#: 站点明确拒绝自动化访问 —— 重试无意义
BLOCKING_STATUS = frozenset({401, 403, 412})
#: 临时性故障 —— 值得退避重试
RETRYABLE_STATUS = frozenset({408, 425, 429})
#: 单次退避上限（秒）。retryInterval 是用户配的，不设顶会出现半小时的干等。
MAX_RETRY_DELAY = 300.0


class FetchBlocked(RuntimeError):
    """站点返回拒绝访问类状态码。重试不会成功，应换 URL 或转人工。"""

    def __init__(self, url: str, statusCode: int):
        self.url = url
        self.statusCode = statusCode
        super().__init__(f"站点拒绝访问（HTTP {statusCode}）：{url}")


class FetchFailed(RuntimeError):
    """重试耗尽后仍然失败。"""

    def __init__(self, url: str, attempts: int, lastError: object):
        self.url = url
        self.attempts = attempts
        self.lastError = lastError
        super().__init__(f"请求 {url} 失败（已重试 {attempts} 次）: {lastError}")


def _isRetryableStatus(statusCode: int) -> bool:
    return statusCode in RETRYABLE_STATUS or 500 <= statusCode < 600


def _retryAfterSeconds(exc: Exception) -> Optional[float]:
    """读响应里的 ``Retry-After``（秒数形式）；没有或格式不认识就返回 None。"""
    resp = getattr(exc, "response", None)
    if resp is None:
        return None
    raw = resp.headers.get("Retry-After", "")
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def _retryDelay(attempt: int, retryInterval: float, exc: Exception) -> float:
    """第 ``attempt`` 次失败后该等多久。

    站点给了 ``Retry-After`` 就照它说的等 —— 那是对方明确的节流要求，比自己
    猜更礼貌；否则按 ``retryInterval`` 指数退避，避免固定间隔在持续故障下
    把请求打成均匀的心跳。
    """
    retryAfter = _retryAfterSeconds(exc)
    if retryAfter is not None:
        return min(retryAfter, MAX_RETRY_DELAY)
    return min(float(retryInterval) * (2 ** (attempt - 1)), MAX_RETRY_DELAY)


def fetchHtml(
    url: str,
    userAgent: str,
    timeout: int = 30,
    maxRetries: int = 3,
    retryInterval: int = 30,
) -> str:
    """获取网页 HTML，带分级重试与编码处理。

    Returns:
        解码后的 HTML 字符串。
    Raises:
        FetchBlocked: 站点返回 401/403/412。
        FetchFailed: 重试耗尽仍失败（含 429/5xx 与网络异常）。
    """
    lastErr: object = None
    for attempt in range(1, maxRetries + 1):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": userAgent},
                timeout=timeout,
            )
            if resp.status_code in BLOCKING_STATUS:
                log.warning("站点拒绝访问 [HTTP %d] %s，不再重试", resp.status_code, url)
                raise FetchBlocked(url, resp.status_code)
            if _isRetryableStatus(resp.status_code):
                raise requests.HTTPError(f"HTTP {resp.status_code}（临时故障，可重试）", response=resp)
            resp.raise_for_status()
            # 优先用 apparent_encoding（requests 自动探测），回退 utf-8
            if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except FetchBlocked:
            raise
        except Exception as e:
            lastErr = e
            log.warning("抓取失败 [%d/%d] %s: %s", attempt, maxRetries, url, e)
            if attempt < maxRetries:
                time.sleep(_retryDelay(attempt, retryInterval, e))
    raise FetchFailed(url, maxRetries, lastErr)


def fetchJson(
    url: str,
    userAgent: str,
    timeout: int = 30,
    maxRetries: int = 3,
    retryInterval: int = 30,
    referer: str = "",
):
    """获取 JSON 接口，与 `fetchHtml` 共用同一套分级重试与拒绝访问语义。

    用于方正 Founder rc-pub 这类开放 JSON API。同样：401/403/412 立即抛
    `FetchBlocked`（不绕过），429/5xx 退避重试，耗尽后抛 `FetchFailed`。

    Returns:
        解析后的 JSON（dict / list，取决于接口）。
    Raises:
        FetchBlocked: 站点返回 401/403/412。
        FetchFailed: 重试耗尽仍失败，或响应不是合法 JSON。
    """
    headers = {"User-Agent": userAgent, "Accept": "application/json"}
    if referer:
        headers["Referer"] = referer
    lastErr: object = None
    for attempt in range(1, maxRetries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code in BLOCKING_STATUS:
                log.warning("接口拒绝访问 [HTTP %d] %s，不再重试", resp.status_code, url)
                raise FetchBlocked(url, resp.status_code)
            if _isRetryableStatus(resp.status_code):
                raise requests.HTTPError(f"HTTP {resp.status_code}（临时故障，可重试）", response=resp)
            resp.raise_for_status()
            return resp.json()
        except FetchBlocked:
            raise
        except Exception as e:
            lastErr = e
            log.warning("接口请求失败 [%d/%d] %s: %s", attempt, maxRetries, url, e)
            if attempt < maxRetries:
                time.sleep(_retryDelay(attempt, retryInterval, e))
    raise FetchFailed(url, maxRetries, lastErr)


def downloadFile(
    url: str,
    savePath: str,
    userAgent: str,
    timeout: int = 60,
    maxRetries: int = 3,
    retryInterval: int = 30,
) -> str:
    """下载二进制文件到指定路径。

    Returns:
        保存路径。
    Raises:
        FetchBlocked: 站点返回 401/403/412。
        FetchFailed: 下载失败。
    """
    lastErr: object = None
    for attempt in range(1, maxRetries + 1):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": userAgent},
                timeout=timeout,
                stream=True,
            )
            if resp.status_code in BLOCKING_STATUS:
                log.warning("站点拒绝下载 [HTTP %d] %s，不再重试", resp.status_code, url)
                raise FetchBlocked(url, resp.status_code)
            if _isRetryableStatus(resp.status_code):
                raise requests.HTTPError(f"HTTP {resp.status_code}（临时故障，可重试）", response=resp)
            resp.raise_for_status()
            with open(savePath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return savePath
        except FetchBlocked:
            raise
        except Exception as e:
            lastErr = e
            log.warning("下载失败 [%d/%d] %s: %s", attempt, maxRetries, url, e)
            if attempt < maxRetries:
                time.sleep(_retryDelay(attempt, retryInterval, e))
    raise FetchFailed(url, maxRetries, lastErr)
