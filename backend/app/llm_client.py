"""云端生成模型的 HTTP 调用（兼容 Chat Completions）。

行为与 scripts/spike_llm.py 一致：非流式、总时限、错误分类。不重试，不切换模型。
错误只暴露分类，不携带上游返回的文字，更不会包含 API 密钥。
"""

import json
import logging
import threading

import httpx

from app.config import Settings
from app.qa_prompt import build_request_body

log = logging.getLogger(__name__)

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ERROR_BODY_BYTES = 8192
# 上游错误体中出现这些词时，按余额或额度用尽处理（例如百炼的 Arrearage、OpenAI 风格的 insufficient_quota）
QUOTA_MARKERS = ("arrearage", "insufficient_quota", "insufficient_balance", "insufficient balance", "余额", "欠费")

AUTH_FAILED = "auth_failed"
QUOTA_EXHAUSTED = "quota_exhausted"
RATE_LIMITED = "rate_limited"
UNAVAILABLE = "unavailable"
TIMEOUT = "timeout"
BAD_RESPONSE = "bad_response"


class LlmError(Exception):
    """kind 为上方六种分类之一。消息固定，不含上游文字。"""

    def __init__(self, kind: str, upstream_status: int | None = None):
        super().__init__(kind)
        self.kind = kind
        self.upstream_status = upstream_status


class _HttpStatusError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(status)
        self.status = status
        self.body = body


def has_quota_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in QUOTA_MARKERS)


def classify_http_status(status: int, body: str) -> str:
    if status == 401:
        return AUTH_FAILED
    if status == 402:
        return QUOTA_EXHAUSTED
    if status in (400, 403, 429) and has_quota_marker(body):
        return QUOTA_EXHAUSTED
    if status == 403:
        return AUTH_FAILED
    if status == 429:
        return RATE_LIMITED
    return UNAVAILABLE


def _payload_error_text(payload) -> str:
    if isinstance(payload, dict) and payload.get("error"):
        err = payload["error"]
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or "")
        return str(err)
    return ""


class LlmClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.provider = settings.llm_provider
        self.model = settings.llm_model.strip()
        self.base_url = settings.llm_base_url.strip().rstrip("/")
        self._api_key = settings.llm_api_key.get_secret_value().strip()
        self.timeout = settings.llm_timeout_seconds
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(
            self.base_url.startswith(("https://", "http://")) and self._api_key and self.model
        )

    def _send(self, messages: list[dict], cancel: threading.Event) -> dict:
        body = build_request_body(self.provider, self.model, messages)
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + self._api_key}
        with httpx.Client(transport=self.transport, timeout=httpx.Timeout(self.timeout), follow_redirects=False) as client:
            with client.stream(
                "POST", self.base_url + "/chat/completions",
                content=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers,
            ) as response:
                failed = response.status_code >= 400
                limit = MAX_ERROR_BODY_BYTES if failed else MAX_RESPONSE_BYTES
                buffer = bytearray()
                for piece in response.iter_bytes():
                    if cancel.is_set():
                        raise TimeoutError("已超过总时限")
                    buffer.extend(piece)
                    if len(buffer) > limit:
                        if failed:
                            break
                        raise LlmError(BAD_RESPONSE)
                if failed:
                    raise _HttpStatusError(response.status_code, bytes(buffer[:limit]).decode("utf-8", errors="replace"))
        try:
            return json.loads(bytes(buffer).decode("utf-8"))
        except ValueError:
            raise LlmError(BAD_RESPONSE) from None

    def _call_with_deadline(self, messages: list[dict]) -> dict:
        cancel = threading.Event()
        box: dict = {}

        def worker() -> None:
            try:
                box["value"] = self._send(messages, cancel)
            except BaseException as exc:
                box["error"] = exc

        thread = threading.Thread(target=worker, name="llm-request", daemon=True)
        thread.start()
        thread.join(self.timeout)
        if thread.is_alive():
            cancel.set()
            raise TimeoutError("超过总时限")
        if "error" in box:
            raise box["error"]
        return box["value"]

    def chat(self, messages: list[dict]) -> tuple[str, dict]:
        """返回模型输出的文本和服务商给出的 Token 用量。失败时抛出 LlmError。"""
        try:
            payload = self._call_with_deadline(messages)
        except LlmError:
            raise
        except _HttpStatusError as exc:
            raise LlmError(classify_http_status(exc.status, exc.body), exc.status) from None
        except (TimeoutError, httpx.TimeoutException):
            raise LlmError(TIMEOUT) from None
        except httpx.HTTPError:
            raise LlmError(UNAVAILABLE) from None
        except Exception as exc:
            log.warning("云端调用出现未预期的异常 (%s)", type(exc).__name__)
            raise LlmError(UNAVAILABLE) from None
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, AttributeError):
            if has_quota_marker(_payload_error_text(payload)):
                raise LlmError(QUOTA_EXHAUSTED) from None
            raise LlmError(BAD_RESPONSE) from None
        usage = payload.get("usage") if isinstance(payload, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        tokens = {
            key: usage[key]
            for key in ("prompt_tokens", "completion_tokens")
            if isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool)
        }
        return content, tokens
