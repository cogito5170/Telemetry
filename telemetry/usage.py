"""공급자 usage -> L0 의 사용량 칸(Anthropic 식 분할). 단위 · 어휘 번역이지 판단이 아니다.

    input_tokens                 캐시 **밖** 입력
    cache_read_input_tokens      캐시 읽기
    cache_creation_input_tokens  캐시 쓰기
    output_tokens                출력 전체(생각 포함)
    thinking_tokens              생각 · 추론

공급자 차이(Sensor state/normalize.canonical_usage 와 같은 대응, OpenAI · Gemini 는 SDK 소스로만 확인 -- 확인수준 D):
    OpenAI  prompt_tokens 는 캐시 포함 -> input = prompt − cached
    Gemini  prompt_token_count 는 캐시 포함, candidates 는 생각 제외, 도구 결과 입력은 따로
            -> input = prompt − cached + tool_use_prompt, output = candidates + thoughts

못 본 칸은 dict 에 넣지 않는다(-> unobserved). 0 으로 메우지 않는다.
OTel(gen_ai.usage.input_tokens = 캐시 **포함** 입력)로는 `otel_usage` 로 더해서 낸다.
"""
from __future__ import annotations


def l0_usage(provider: str, u: dict) -> "tuple[dict, list]":
    """-> (칸 dict, 원천이 null 로 준 칸들). provider 는 usage 의 **꼴** 이름이다(anthropic · openai · gemini · otel)."""
    u = u or {}
    if provider == "otel":
        # 이미 정규화된 OTel 식(MS canonical Usage): input = 캐시 포함 전체, cached_input = 캐시 읽기, output = 생각 포함.
        # 캐시 쓰기가 따로 없어 '캐시 밖 입력' 을 셈할 수 없다 -- input_tokens 는 못 봄으로 두고 전체를 total_input_tokens 에
        out = {}
        for src, dst in (("input_tokens", "total_input_tokens"), ("cached_input_tokens", "cache_read_input_tokens"),
                         ("output_tokens", "output_tokens")):
            if u.get(src) is not None:
                out[dst] = u[src]
        return out, []
    if provider in ("anthropic", "claude"):
        out, nulls = {}, []
        for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"):
            if k in u:
                (nulls.append(k) if u[k] is None else out.__setitem__(k, u[k]))
        od = u.get("output_tokens_details")
        if isinstance(od, dict) and "thinking_tokens" in od:
            (nulls.append("thinking_tokens") if od["thinking_tokens"] is None
             else out.__setitem__("thinking_tokens", od["thinking_tokens"]))
        cc = u.get("cache_creation")
        if isinstance(cc, dict):
            for src, dst in (("ephemeral_5m_input_tokens", "cache_creation_5m_input_tokens"),
                             ("ephemeral_1h_input_tokens", "cache_creation_1h_input_tokens")):
                if src in cc:
                    (nulls.append(dst) if cc[src] is None else out.__setitem__(dst, cc[src]))
        st = u.get("server_tool_use")
        if isinstance(st, dict):
            out["server_tool_requests"] = sum(v for v in st.values() if isinstance(v, int))
        if isinstance(u.get("iterations"), list):
            out["iterations"] = len(u["iterations"])
        return out, nulls
    if provider == "openai":
        pt = u.get("prompt_tokens", u.get("input_tokens"))
        det = u.get("prompt_tokens_details") or u.get("input_tokens_details") or {}
        cd = u.get("completion_tokens_details") or u.get("output_tokens_details") or {}
        out = {}
        cached = det.get("cached_tokens")
        if pt is not None and cached is not None:
            out["input_tokens"] = pt - cached
            out["cache_read_input_tokens"] = cached
        if det.get("cache_write_tokens") is not None:
            out["cache_creation_input_tokens"] = det["cache_write_tokens"]
        ct = u.get("completion_tokens", u.get("output_tokens"))
        if ct is not None:
            out["output_tokens"] = ct
        if cd.get("reasoning_tokens") is not None:
            out["thinking_tokens"] = cd["reasoning_tokens"]
        return out, []
    if provider == "gemini":
        g = {k: u.get(k) for k in ("prompt_token_count", "cached_content_token_count", "candidates_token_count",
                                   "thoughts_token_count", "tool_use_prompt_token_count")}
        out = {}
        if g["prompt_token_count"] is not None and g["cached_content_token_count"] is not None:
            out["input_tokens"] = (g["prompt_token_count"] - g["cached_content_token_count"]
                                   + (g["tool_use_prompt_token_count"] or 0))
            out["cache_read_input_tokens"] = g["cached_content_token_count"]
        if g["candidates_token_count"] is not None:
            out["output_tokens"] = g["candidates_token_count"] + (g["thoughts_token_count"] or 0)
        if g["thoughts_token_count"] is not None:
            out["thinking_tokens"] = g["thoughts_token_count"]
        return out, []
    raise ValueError(f"모르는 공급자 {provider!r}")


def otel_usage(data: dict) -> dict:
    """llm.response 의 data -> OTel GenAI 이름(Development). 못 본 것이 섞이면 그 합은 내지 않는다."""
    i, r, w = data.get("input_tokens"), data.get("cache_read_input_tokens"), data.get("cache_creation_input_tokens")
    out = {}
    if None not in (i, r, w):
        out["gen_ai.usage.input_tokens"] = i + r + w        # OTel: "SHOULD include ... cached tokens"
    elif data.get("total_input_tokens") is not None:
        out["gen_ai.usage.input_tokens"] = data["total_input_tokens"]
    if r is not None:
        out["gen_ai.usage.cache_read.input_tokens"] = r
    if w is not None:
        out["gen_ai.usage.cache_write.input_tokens"] = w
    if data.get("output_tokens") is not None:
        out["gen_ai.usage.output_tokens"] = data["output_tokens"]
    if data.get("response_id") is not None:
        out["gen_ai.response.id"] = data["response_id"]
    if data.get("stop_reason") is not None:
        out["gen_ai.response.finish_reasons"] = [data["stop_reason"]]
    return out
