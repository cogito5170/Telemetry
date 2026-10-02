"""공급자 오류 -> 정준 어휘. **번역이지 판단이 아니다**: 출처 있는 대응표만 쓰고, 원래 값(HTTP 상태 · 공급자 코드)을 함께 남긴다.

'실패했다' · '다시 하라' 는 여기서 말하지 않는다. 예: DEADLINE_EXCEEDED 는 google.rpc 주석대로
"may be returned even if the operation has completed successfully" -- 그 뜻을 정하는 것은 Sensor 다.

표는 Sensor(llmsensor/providers) 의 것을 옮겼다. 출처:
    anthropic  claude-api 스킬 shared/error-codes.md
    gemini     googleapis google/rpc/code.proto + error_details.proto RetryInfo + AIP-193
    openai     1 차 문서를 못 읽었다 -- HTTP 429 만(다른 두 공급자의 1 차 자료가 같은 뜻으로 쓴다), 나머지 UNKNOWN
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ErrorCode(str, Enum):
    RATE_LIMITED = "RATE_LIMITED"
    OVERLOADED = "OVERLOADED"
    UNAVAILABLE = "UNAVAILABLE"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    INVALID_REQUEST = "INVALID_REQUEST"
    AUTH = "AUTH"
    PERMISSION = "PERMISSION"
    NOT_FOUND = "NOT_FOUND"
    BILLING = "BILLING"
    TOO_LARGE = "TOO_LARGE"
    SERVER_ERROR = "SERVER_ERROR"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"          # 출처 있는 대응이 없다 -- 원래 값은 provider_code · http_status 에


K = ErrorCode


@dataclass(frozen=True)
class Translated:
    provider: str
    error_code: ErrorCode
    http_status: "int | None"
    provider_code: "str | None"
    retry_after_ms: "float | None"    # 공급자가 **선언한** 대기. 없으면 None
    source: str


ANTHROPIC_SOURCE = "claude-api skill shared/error-codes.md"
ANTHROPIC_BY_TYPE = {"invalid_request_error": K.INVALID_REQUEST, "authentication_error": K.AUTH, "billing_error": K.BILLING,
                     "permission_error": K.PERMISSION, "not_found_error": K.NOT_FOUND, "request_too_large": K.TOO_LARGE,
                     "rate_limit_error": K.RATE_LIMITED, "api_error": K.SERVER_ERROR, "overloaded_error": K.OVERLOADED}
ANTHROPIC_BY_STATUS = {400: K.INVALID_REQUEST, 401: K.AUTH, 402: K.BILLING, 403: K.PERMISSION, 404: K.NOT_FOUND,
                       413: K.TOO_LARGE, 429: K.RATE_LIMITED, 500: K.SERVER_ERROR, 529: K.OVERLOADED}
GEMINI_SOURCE = "google/rpc/code.proto + error_details.proto RetryInfo + AIP-193"
GEMINI_BY_RPC = {"INVALID_ARGUMENT": K.INVALID_REQUEST, "FAILED_PRECONDITION": K.INVALID_REQUEST,
                 "OUT_OF_RANGE": K.INVALID_REQUEST, "UNAUTHENTICATED": K.AUTH, "PERMISSION_DENIED": K.PERMISSION,
                 "NOT_FOUND": K.NOT_FOUND, "RESOURCE_EXHAUSTED": K.RATE_LIMITED, "UNAVAILABLE": K.UNAVAILABLE,
                 "DEADLINE_EXCEEDED": K.DEADLINE_EXCEEDED, "INTERNAL": K.SERVER_ERROR, "UNKNOWN": K.SERVER_ERROR,
                 "DATA_LOSS": K.SERVER_ERROR, "CANCELLED": K.CANCELLED}
GEMINI_BY_STATUS = {400: K.INVALID_REQUEST, 401: K.AUTH, 403: K.PERMISSION, 404: K.NOT_FOUND, 429: K.RATE_LIMITED,
                    499: K.CANCELLED, 500: K.SERVER_ERROR, 503: K.UNAVAILABLE, 504: K.DEADLINE_EXCEEDED}
OPENAI_SOURCE = "HTTP 429 only (OpenAI docs not read -- U); same meaning in google/rpc/code.proto and Anthropic error-codes.md"


def _seconds_ms(v):
    try:
        return float(v) * 1000 if v is not None else None
    except (TypeError, ValueError):
        return None                 # HTTP 날짜 꼴 등 -- 문서에 '초' 로만 적혀 있어 추측하지 않는다


def _duration_ms(s):
    """google.protobuf.Duration 의 JSON 꼴 '30s' · '1.5s'."""
    if isinstance(s, str) and s.endswith("s"):
        try:
            return float(s[:-1]) * 1000
        except ValueError:
            return None
    return None


def translate(provider: str, http_status=None, body=None, headers=None) -> Translated:
    body = body if isinstance(body, dict) else {}
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    if provider == "anthropic":
        typ = err.get("type")
        return Translated(provider, ANTHROPIC_BY_TYPE.get(typ) or ANTHROPIC_BY_STATUS.get(http_status, K.UNKNOWN),
                          http_status, typ, _seconds_ms(h.get("retry-after")), ANTHROPIC_SOURCE)
    if provider == "gemini":
        rpc = err.get("status")
        st = http_status if http_status is not None else err.get("code")
        ra = None
        for d in err.get("details") or []:
            if isinstance(d, dict) and str(d.get("@type", "")).endswith("google.rpc.RetryInfo"):
                ra = _duration_ms(d.get("retryDelay"))
        return Translated(provider, GEMINI_BY_RPC.get(rpc) or GEMINI_BY_STATUS.get(st, K.UNKNOWN), st, rpc, ra,
                          GEMINI_SOURCE)
    if provider == "openai":
        return Translated(provider, K.RATE_LIMITED if http_status == 429 else K.UNKNOWN, http_status, err.get("type"),
                          None, OPENAI_SOURCE)
    return Translated(provider, K.UNKNOWN, http_status, err.get("type") or err.get("status"), None,
                      f"no table for provider {provider!r}")
