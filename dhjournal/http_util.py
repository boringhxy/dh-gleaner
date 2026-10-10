"""HTTP 请求工具 — 带 UA、分级重试、编码处理。

重试策略按状态码分级，避免在「对方明确拒绝自动化访问」时空等：

- ``401/403/412``：站点拒绝访问（412 常见于中文期刊站点的反爬前置检查），
  重试不会变好，**立刻放弃并抛出 `FetchBlocked`**，让上层换 URL 或转人工。
- ``408/425/429/5xx``：临时性故障，按 `retryInterval` 退避重试。
- 其他异常（连接超时、DNS 失败等）：照旧重试。

抛出的异常都继承 `RuntimeError`，与改造前的调用方兼容。
"""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

#: 站点明确拒绝自动化访问 —— 重试无意义
BLOCKING_STATUS = frozenset({401, 403, 412})
#: 临时性故障 —— 值得退避重试
RETRYABLE_STATUS = frozenset({408, 425, 429})


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
                time.sleep(retryInterval)
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
                time.sleep(retryInterval)
    raise FetchFailed(url, maxRetries, lastErr)
