"""L0 Telemetry -- "무슨 일이 일어났나". Sensor(L1) 아래의 독립 관측 층.

    L0  Telemetry  무슨 일이 일어났나          ← 이 패키지. 관측 사실만
    L1  Sensor     그 관측이 무엇을 뜻하나       llmsensor (sensing 팩 · 문턱 · 잔차)
    L2  State      지금 시스템이 어떤 상태인가    llmsensor.state · ms.usage_model
    L3  DC         이번 결정에 무엇이 필요한가    dc
    L4  Policy     그래서 무엇을 할 것인가        ms
    L5  Action     실행 -- 그 결과는 다시 L0 로

    catalog   사건 종류 · 칸 · 칸마다 출처 종류(reported · declared · measured · translated · ref). 해석 어휘 금지
    event     봉투 · 닫힌 꼴 검사 · unobserved / reported_null
    collect   원천(Claude Code JSONL · stream-json · SWE-agent) -> 사건
    recorder  프로세스 안 계측(도구 · 모형 호출 · 생존 박동 · 의존 탐침 · 행동)
    ledger    덧붙이기만 하는 JSONL 원장
    errors    공급자 오류 -> 정준 어휘(번역, 출처 있는 표만)
    usage     공급자 usage -> 사용량 칸 · OTel 이름으로 내보내기
    compat    사건 -> Sensor 꼴 v3 레코드 (Sensor 의 State 엔진이 그대로 앉는다)

표준 라이브러리만 쓴다. 위층(llmsensor · ms · dc)을 import 하지 않는다 -- 시험이 붙든다.
"""
from .catalog import EVENTS, SPEC
from .event import check, make, observed
from .ledger import JsonlSink, MemorySink
from .recorder import Recorder

__all__ = ["EVENTS", "SPEC", "check", "make", "observed", "Recorder", "JsonlSink", "MemorySink"]
