"""사건 목록 -- L0 가 적을 수 있는 사건의 종류와 그 칸. **여기 없는 칸은 적을 수 없다**(닫힌 꼴).

칸마다 출처 종류(origin)가 붙는다. 다섯뿐이다:

    reported    원천이 준 수 · 시각 · 이름                 input_tokens · cost_usd · tool_name
    declared    원천이 **스스로 붙인** 분류 · 상태 · 한도      stop_reason · rate_limit 상태 문자열 · "Command timed out after"
                -- 원천의 주장이다. 믿을지는 Sensor 가 정한다
    measured    수집기가 직접 잰 것(시계 · 글자 수 · 개수)    elapsed_ms · output_chars · stream_chunks
    translated  출처 있는 대응표로 어휘만 옮긴 것            error_code(HTTP 429 -> RATE_LIMITED, google.rpc)
                -- 원래 값은 같은 사건의 reported 칸에 남는다
    ref         사건을 잇는 식별자(뜻 없음)                 call_index · tool_index · action_ref · decision_ref

**없는 것: 판단.** 문턱 비교 · 등급 · 위험 · 건강 · 추천 · 결정은 출처 종류가 없다 -- L1(Sensor) 이상의 일이다.
그래서 칸 이름에도 그 어휘를 못 쓴다(FORBIDDEN, `check_catalog` 와 시험이 붙든다).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SPEC = "l0-telemetry/1"
ORIGINS = ("reported", "declared", "measured", "translated", "ref")
TYPES = ("int", "num", "str", "bool")
TIME_BASES = ("unix_ms", "monotonic_ms", None)


@dataclass(frozen=True)
class F:
    type: str
    origin: str
    note: str = ""


def _f(t, o, note=""):
    return F(t, o, note)


R, D, M, T, X = "reported", "declared", "measured", "translated", "ref"

# 모형 사용량 -- Anthropic 식으로 셋을 갈라 둔다(가장 잘게 쪼갠 꼴. OTel 의 '캐시 포함 입력' 은 더해서 낸다)
USAGE = {
    "input_tokens": _f("int", R, "캐시 **밖**에서 새로 읽은 입력"),
    "total_input_tokens": _f("int", R, "캐시 읽기 · 쓰기를 **포함한** 전체 입력(OTel gen_ai.usage.input_tokens). "
                                       "원천이 셋으로 갈라 주지 않을 때만 -- 갈라서 지어내지 않는다"),
    "cache_read_input_tokens": _f("int", R, "캐시에서 읽은 입력"),
    "cache_creation_input_tokens": _f("int", R, "캐시에 새로 쓴 입력"),
    "cache_creation_5m_input_tokens": _f("int", R), "cache_creation_1h_input_tokens": _f("int", R),
    "output_tokens": _f("int", R, "출력 전체(생각 포함)"),
    "thinking_tokens": _f("int", R, "생각 · 추론 출력"),
    "server_tool_requests": _f("int", R), "iterations": _f("int", M, "usage.iterations 목록의 길이"),
}

EVENTS: "dict[str, dict[str, F]]" = {
    # ── 모형 호출 ────────────────────────────────────────────────────────────
    "llm.request": {
        "call_index": _f("int", X), "attempt": _f("int", M, "같은 call_index 에서 몇 번째 보냄인가(0 부터)"),
        "provider": _f("str", R), "model": _f("str", R), "prompt_chars": _f("int", M),
    },
    "llm.response": {
        "call_index": _f("int", X), "response_id": _f("str", X), "provider": _f("str", R), "model": _f("str", R),
        **USAGE,
        "stop_reason": _f("str", D, "원천이 말한 끝난 까닭"),
        "status_code": _f("int", R, "HTTP 상태(프로세스 안 계측일 때)"),
        "t_start_ms": _f("num", M, "그 응답을 처음 본 시각"), "t_end_ms": _f("num", M, "마지막으로 본 시각"),
        "elapsed_ms": _f("num", M, "수집기가 한 시계로 보냄~받음을 잰 값(로그 원천에서는 못 잰다)"),
        "first_chunk_ms": _f("num", M, "message_start ~ 첫 조각"), "stream_chunks": _f("int", M),
        "stream_thinking_estimate": _f("int", R, "생성 도중 런타임 추정 -- 최종값 아님"),
        "thinking_duration_ms": _f("num", R),
        "tool_calls_per_message": _f("int", M), "output_text_chars": _f("int", M),
    },
    "llm.error": {
        "call_index": _f("int", X), "attempt": _f("int", M), "provider": _f("str", R),
        "http_status": _f("int", R), "provider_code": _f("str", R, "공급자 고유 이름(rate_limit_error · RESOURCE_EXHAUSTED)"),
        "error_code": _f("str", T, "정준 어휘(errors.ErrorCode). 대응표에 없으면 UNKNOWN"),
        "error_code_source": _f("str", X, "대응표의 출처"),
        "retry_after_ms": _f("num", D, "공급자가 선언한 대기"),
        "exception": _f("str", R, "예외 종류 이름(메시지는 안 남긴다)"),
        "elapsed_ms": _f("num", M),
    },
    # ── 도구 ────────────────────────────────────────────────────────────────
    "tool.start": {
        "call_index": _f("int", X, "그 도구를 부른 모형 호출"), "tool_index": _f("int", X, "실행 안 도구 순번"),
        "tool_name": _f("str", R), "tool_head": _f("str", M, "이름:겨냥 -- 겨냥은 맨 프로그램 이름만 평문, 나머지는 #해시"),
        "tool_sig": _f("str", M, "이름 + 인자 정규형의 열쇠 해시"), "tool_input_chars": _f("int", M),
    },
    "tool.end": {
        "tool_index": _f("int", X),
        "is_error": _f("bool", R, "런타임의 오류 깃발"), "interrupted": _f("bool", R),
        "timed_out": _f("bool", D, "런타임이 **스스로** 시간 초과를 선언했나. 구조화 칸(timedOutAfterMs)이 먼저, 글 문구는 "
                                   "is_error 이고 결과가 'Exit code' 로 시작할 때만. 경과 시간을 문턱에 비교한 값이 아니다"),
        "declared_timeout_ms": _f("num", D, "런타임이 선언한 시간 한도(timedOutAfterMs)"),
        "moved_to_background": _f("bool", R, "시간 한도를 넘은 명령을 런타임이 죽이지 않고 백그라운드로 옮겼다(backgroundTaskId)"),
        "background_task_ref": _f("str", X, "옮겨진 백그라운드 작업의 id"),
        "exit_code": _f("int", R), "exception": _f("str", R, "예외 종류 이름(메시지는 안 남긴다)"),
        "output_chars": _f("int", M), "reported_duration_ms": _f("num", R),
        "elapsed_ms": _f("num", M, "수집기가 한 시계로 시작~끝을 잰 값"),
    },
    # ── 실행 ────────────────────────────────────────────────────────────────
    "run.start": {"model": _f("str", R), "provider": _f("str", R)},
    "run.end": {
        "decision_ref": _f("str", X, "이 실행을 낳은 결정 기록의 id(MS DecisionRecord.id). 결정의 내용은 L0 에 없다"),
        "model": _f("str", R), "run_duration_ms": _f("num", R), "api_duration_ms": _f("num", R),
        "api_duration_without_retries_ms": _f("num", R), "ttft_ms": _f("num", R), "num_turns": _f("int", R),
        "cost_usd": _f("num", R, "**원천이 보고한** 비용. 단가표로 계산한 비용은 L0 가 아니다"),
        "terminal_reason": _f("str", D), "result_subtype": _f("str", D), "is_error": _f("bool", R),
        "api_error_status": _f("str", R), "permission_denials": _f("int", M),
        "tokens_sent": _f("int", R), "tokens_received": _f("int", R), "api_calls": _f("int", R),
        "reported_input_tokens": _f("int", R), "reported_output_tokens": _f("int", R),
        "reported_cache_read_input_tokens": _f("int", R), "reported_cache_creation_input_tokens": _f("int", R),
    },
    # 실행 도중의 누적 스냅숏(Claude Code cost-state). 끝이 아니다 -- 사건 시각(at)이 스냅숏 시각
    "run.snapshot": {
        "run_duration_ms": _f("num", R), "api_duration_ms": _f("num", R), "api_duration_without_retries_ms": _f("num", R),
        "cost_usd": _f("num", R), "reported_input_tokens": _f("int", R), "reported_output_tokens": _f("int", R),
        "reported_cache_read_input_tokens": _f("int", R), "reported_cache_creation_input_tokens": _f("int", R),
    },
    # ── 차례 경계 (BD-47: L1 liveness 의 입력. 차례가 열려 있나 · 무음 길이는 L1 이 이 사건들에서 잰다) ──
    "input.received": {
        "input_chars": _f("int", M, "받은 입력의 길이(글은 안 남긴다)"),
    },
    "turn.start": {
        "turn_index": _f("int", R, "런타임이 매긴 차례 번호"), "prompt_index": _f("int", R),
        "turn_origin": _f("str", D, "런타임이 붙인 차례의 출처 이름 그대로(human · task_notification …)"),
        "input_chars": _f("int", M),
    },
    "turn.end": {
        "marker": _f("str", R, "끝을 선언한 원천 줄의 종류(stop_hook_summary · result)"),
        "stop_hook_count": _f("int", R),
    },
    "turn.continued": {
        "marker": _f("str", R), "stop_hook_count": _f("int", R, "Stop 훅이 끝을 막아 차례가 이어졌다"),
    },
    "source.closed": {
        "exit_code": _f("int", R, "원천 프로세스의 종료 코드(수집기가 받았을 때만)"),
    },
    # ── 런타임 · 공급자가 선언한 한도와 사용률 ────────────────────────────────
    "runtime.limits": {
        "context_window": _f("int", D), "max_output_tokens": _f("int", D), "autocompact_threshold": _f("int", D),
    },
    # 요금 한도는 실행이 아니라 **계정**의 것이다(BD-32) -- 실행 실체에 달면 '이 실행이 소모했다' 로 잘못 읽힌다. 실체는 L2 가 정한다
    "provider.rate_limit": {
        "utilization": _f("num", R), "declared_status": _f("str", D, "런타임의 상태 문자열 그대로(allowed_warning · rejected ...)"),
        "declared_threshold": _f("num", D), "resets_at_ms": _f("num", D),
        "limit_type": _f("str", D, "한도의 종류 이름 그대로(five_hour ...)"),
        "overage_status": _f("str", D), "overage_disabled_reason": _f("str", D),
        "fallback_available": _f("bool", D, "런타임이 대체 경로가 있다고 선언했나"),
    },
    # ── 런타임 자신의 행동 (BD-53) ──
    "runtime.compaction": {
        "trigger": _f("str", D, "auto · manual -- 런타임이 붙인 이름 그대로"),
        "pre_tokens": _f("int", R), "post_tokens": _f("int", R), "duration_ms": _f("num", R),
    },
    "runtime.status": {
        "declared_status": _f("str", D, "런타임이 알린 진행 상태 그대로(requesting ...)"),
    },
    "input.removed": {
        "reason": _f("str", D, "줄에 선 입력을 런타임이 뺀 까닭 그대로(absorbed_mid_turn ...)"),
    },
    # ── 앞으로의 관측: 생존 · 회복 · 의존 · 행동 결과 (L1 의 liveness · recovery · dependency · action_outcome 의 근거) ──
    "heartbeat": {"emitter": _f("str", X), "beat": _f("int", M, "그 emitter 의 몇 번째 박동"),
                  "heartbeat_flag": _f("bool", D, "원천이 이 진행 신호에 박동 표시를 붙였나(cc_stream tool_progress.heartbeat)"),
                  "reported_elapsed_ms": _f("num", R, "원천이 함께 보고한 경과(tool_progress.elapsed_time_seconds)")},
    "dependency.probe": {
        "target": _f("str", M, "#해시"), "status_code": _f("int", R), "error_code": _f("str", T),
        "elapsed_ms": _f("num", M),
    },
    "action.dispatch": {
        "action_ref": _f("str", X), "decision_ref": _f("str", X, "어느 결정에서 나왔나 -- id 만. 결정의 내용 · 까닭은 L0 에 없다"),
        "action_type": _f("str", R, "실행기가 **실제로 실행한** 행동의 이름"), "target": _f("str", M, "#해시"),
    },
    "action.result": {
        "action_ref": _f("str", X), "is_error": _f("bool", R), "exit_code": _f("int", R), "status_code": _f("int", R),
        "exception": _f("str", R), "output_chars": _f("int", M), "elapsed_ms": _f("num", M),
    },
}

# ── 해석 어휘 금지 ───────────────────────────────────────────────────────────
# 칸 · 사건 이름을 '_' · '.' 로 쪼갠 낱말 가운데 이것이 있으면 안 된다. 이것들은 L1(Sensor) 이상의 말이다
FORBIDDEN = frozenset({
    "health", "healthy", "unhealthy", "risk", "risky", "should", "verdict", "policy", "recommend", "recommended",
    "recommendation", "score", "severity", "anomaly", "anomalous", "degraded", "state", "quality", "confidence",
    "pressure", "alert", "decision", "suggest", "suggested", "good", "bad", "ok", "slow", "fast", "normal", "abnormal",
    "exceeded", "violation", "violated", "warning", "critical", "stale", "stuck", "loop", "success", "failure",
    "failed",
    # 생존 판정 어휘(BD-47) -- 차례가 열려 있나 · 멈췄나 · 살아 있나는 L1 liveness 가 L0 사건에서 잰다
    "alive", "dead", "stalled", "hung", "idle", "active", "liveness",
})
# 문턱 · 한도 낱말은 **원천이 선언했을 때만**(declared). 우리 문턱은 L0 에 없다
THRESHOLD_WORDS = frozenset({"threshold", "limit", "slo", "budget", "max", "window", "deadline", "timeout"})
_SPLIT = re.compile(r"[._]")


def words(name: str) -> "list[str]":
    return [w for w in _SPLIT.split(name.lower()) if w]


def name_problems(name: str, f: "F | None" = None) -> "list[str]":
    ws = words(name)
    out = []
    bad = [w for w in ws if w in FORBIDDEN]
    if bad and not (f is not None and f.origin == "ref" and name.endswith("_ref")):
        out.append(f"{name}: 해석 어휘 {bad}")          # decision_ref 처럼 뜻 없는 id 만 예외
    th = [w for w in ws if w in THRESHOLD_WORDS]
    if th and f is not None and f.origin != "declared":
        out.append(f"{name}: 문턱 · 한도 낱말 {th} 은 원천이 선언한 칸에만(origin={f.origin})")
    return out


def check_catalog(events=None) -> "list[str]":
    errs = []
    for et, fields in (events or EVENTS).items():
        errs += [f"사건 {e}" for e in name_problems(et)]
        for k, f in fields.items():
            if f.origin not in ORIGINS:
                errs.append(f"{et}.{k}: 출처 종류 {f.origin!r}")
            if f.type not in TYPES:
                errs.append(f"{et}.{k}: 형 {f.type!r}")
            errs += [f"{et}.{e}" for e in name_problems(k, f)]
    return errs
