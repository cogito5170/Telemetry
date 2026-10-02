# Telemetry (L0) -- "무슨 일이 일어났나"

> **Telemetry 는 "무슨 일이 있었는가", Sensor 는 "그 관측이 무엇을 의미하는가", State 는 "현재 시스템이 어떤 상태인가",
> DC 는 "이번 결정에 무엇이 필요한가", Policy 는 "그래서 무엇을 할 것인가" 다.** (사용자, 2026-10-02)

Telemetry 는 Sensor 와 별개의 시스템이 아니다. **Sensor 의 가장 아래 관측 층을 따로 떼어 낸 것**이다. 떼는 까닭은 하나다:
Sensor 와 Policy 를 가르려면, 그 둘 어느 쪽의 판단도 들어 있지 않은 **원 증거**가 먼저 있어야 한다.
선행조사: [`paper/선행조사/Telemetry.md`](../paper/선행조사/Telemetry.md).

## 1. 층

```
L0  Telemetry   무슨 일이 일어났나            raw observations         ← 이 저장소
     │
L1  Sensor      그 관측이 무엇을 뜻하나         interpreted observations  Sensor (llmsensor.sensing 팩 · 문턱 · 잔차)
     │
L2  State       지금 시스템이 어떤 상태인가      maintained condition      llmsensor.state (TTL · STALE · 히스테리시스) · ms.usage_model
     │
L3  DC          이번 결정에 무엇이 필요한가      decision-specific projection   DC
     │
L4  Policy      그래서 무엇을 할 것인가                                    MS (CR · Policy · Arbitrate · Guard)
     │
L5  Action      실행                                                      MS Tool · Action Executor
     │
     └──────────► L0 Telemetry  (Action 의 결과는 다시 관측으로 들어온다 -- 닫힌 고리)
```

위층은 아래층만 본다. **L0 는 아무것도 위로 보지 않는다** -- llmsensor · ms · dc 를 import 하지 않는다(시험이 붙든다).

## 2. L0 의 규칙

| # | 규칙 | 어떻게 붙드나 |
|---|---|---|
| 1 | **관측 사실만.** 문턱 비교 · 등급 · 건강 · 위험 · 추천 · 결정은 없다 | 칸 이름의 해석 어휘 금지(`catalog.FORBIDDEN`) · 닫힌 꼴 |
| 2 | **칸마다 출처 종류가 있다**: `reported`(원천이 준 수 · 시각) · `declared`(원천이 **스스로** 붙인 분류 · 상태 · 한도) · `measured`(수집기가 잰 시계 · 개수) · `translated`(출처 있는 대응표로 어휘만 옮김) · `ref`(뜻 없는 식별자) | `catalog.check_catalog` |
| 3 | **우리의 문턱은 L0 에 없다.** 문턱 · 한도 낱말(threshold · limit · slo · budget · max · window · deadline · timeout)은 원천이 선언한 칸에만 | `name_problems` |
| 4 | **못 봄 ≠ 0 ≠ 보고된 null.** null 인 칸은 `unobserved` 와 `reported_null` 중 정확히 한 곳에. 기본값으로 메우지 않는다 | `event.check` |
| 5 | **닫힌 꼴.** 목록에 없는 사건 종류 · 칸 · 봉투 칸은 적을 수 없다 | `event.make` 가 KeyError |
| 6 | **덧붙이기만 하는 원장.** 위층은 원장을 다시 읽어 언제든 재현한다. 문턱을 바꿔도 원장은 그대로 | `ledger` · 시험 `TimeoutIsASensorQuestion` |
| 7 | **시작도 적는다.** `tool.start` · `llm.request` · `action.dispatch` 가 있고 끝 사건이 없으면, 그 빈자리 자체가 증거다(liveness). 끝을 지어내지 않는다 | 시험 `test_start_without_end_is_kept` |
| 8 | **겨냥 글은 남기지 않는다.** 경로 · URL · 패턴 · 검색어는 열쇠 해시. 평문은 맨 프로그램 이름뿐. 예외 메시지도 안 남긴다(종류 이름만) | `hashing` · 시험 |

### 'declared' 를 따로 두는 까닭

`stop_reason = "max_tokens"`, 런타임의 `"allowed_warning"`, Bash 결과의 `"Command timed out after"` 는 **원천의 주장**이다.
그 주장이 있었다는 것은 사실이라 L0 에 적는다. 그것을 믿을지 · 어떤 뜻으로 받을지는 L1 이 정한다.
반대로 **우리가** 경과 시간을 30 s 에 비교해 얻은 '시간 초과' 는 판단이라 L0 에 없다.

## 3. 사건 봉투

```json
{"spec": "l0-telemetry/1", "id": "r17:7", "type": "llm.response", "run_id": "r17", "seq": 7,
 "source": "inproc:ms", "at": 1759363201840.0, "time_base": "unix_ms",
 "data": {"call_index": 0, "provider": "anthropic", "input_tokens": 1000, "cache_read_input_tokens": 200,
          "output_tokens": 430, "status_code": 200, "elapsed_ms": 1840, "stop_reason": "end_turn", "...": null},
 "unobserved": ["first_chunk_ms", "..."], "reported_null": []}
```

CloudEvents 처럼 `type` 은 **일어난 일**의 종류이고, `id = run_id:seq` 는 한 원장 안에서 유일하다. `at` 은 그 일을 본 시각
(`time_base`: unix_ms · monotonic_ms · 원천에 시각이 없으면 null -- 그때 순서는 seq 가 준다).
**seq 는 원천에 나온 차례다**(2026-10-02, CMD-T2): 로그 수집기는 원천 줄 번호로 늘어놓는다 -- 모형 호출은 첫 줄 자리, 도구 시작 · 끝 ·
차례 경계 · 실행 단위 사건은 제 줄 자리. 그래서 `at`(모형 호출은 마지막으로 본 시각)이 seq 를 따라 꼭 늘지는 않는다.

## 4. 사건 목록 (`telemetry/catalog.py`)

| 사건 | 무엇 | 지금 내는 곳 | L1 에서 읽을 팩 |
|---|---|---|---|
| `llm.request` | 모형에 보냄(몇 번째 시도인가) | Recorder | execution · recovery |
| `llm.response` | 응답 하나 -- 토큰(캐시 밖 · 읽기 · 쓰기 5m/1h · 출력 · 생각. 원천이 갈라 주지 않으면 `total_input_tokens` 만) · 끝난 까닭 · HTTP 상태 · 시각 · 경과 | 세 수집기 · Recorder(MS 런타임) | token · latency · cost · provider |
| `llm.error` | 공급자 오류 -- HTTP 상태 · 공급자 코드(원래 값) · 정준 코드(번역, 볼 것이 없으면 못 봄) · 선언된 대기 · 예외 종류 | Recorder(MS 런타임) · cc_jsonl(런타임이 끼운 API 오류 줄) | provider · recovery |
| `tool.start` · `tool.end` | 도구 호출과 결과 -- 오류 깃발 · 중단 · 선언된 시간 초과(구조화 칸 `timedOutAfterMs` 먼저) · 선언된 시간 한도 · 백그라운드로 옮김 · 종료 코드 · 예외 종류 · 출력 길이 · 경과 | 세 수집기 · Recorder | execution · latency · liveness |
| `run.start` · `run.end` | 실행 시작 · 끝 요약(런타임이 준 값만. 합계를 우리가 내지 않는다). `run.end.decision_ref` = 그 실행을 낳은 결정 기록 id | cc_stream · sweagent · Recorder(MS 런타임) | execution · cost |
| `run.snapshot` | 실행 도중의 누적 스냅숏(Claude Code cost-state -- 끝이 아니다) | cc_jsonl | cost |
| `runtime.limits` | 런타임이 선언한 맥락 창 · 최대 출력 · 자동 압축 문턱 | cc_stream | token |
| `provider.rate_limit` | **계정**의 요금 한도(BD-32) -- 사용률 · 상태 문자열 · 문턱 · 한도 종류(five_hour …) · 초과 사용 상태 · 대체 경로. **사건마다** 따로 | cc_stream(`rate_limit_event`) · cc_jsonl(429 줄의 `quotaLimits`) | provider |
| `input.received` | 런타임이 입력을 받아 줄에 세움(글은 길이만) | cc_jsonl(`queue-operation enqueue`) | liveness |
| `turn.start` | 입력이 대화에 들어가 차례가 열림 -- 런타임이 매긴 차례 · 프롬프트 번호, 차례 출처 이름(human · task_notification …) | cc_jsonl(사람 · 알림 입력 줄. isMeta · 하위 에이전트 줄 제외) · cc_stream(`system/init`) | liveness |
| `turn.end` | 런타임이 차례 끝을 선언함(`marker`: stop_hook_summary · result) | cc_jsonl(Stop 훅 요약, 막히지 않았을 때) · cc_stream(`result`) | liveness |
| `turn.continued` | Stop 훅이 끝을 막아 차례가 이어짐 | cc_jsonl(`preventedContinuation: true`) | liveness |
| `source.closed` | 원천의 흐름이 닫힘(종료 코드) -- **수집기가 닫힘을 적었을 때만**. 파일 끝은 닫힘이 아니다 | cc_stream(캡처의 `{"_t", "closed": true, "returncode"}` 줄) | liveness |
| `heartbeat` | 런타임이 '진행 중' 이라고 보낸 신호(emitter 마다 번호 · 원천의 박동 표시 · 원천이 보고한 경과) | Recorder · cc_stream(`tool_progress`) | liveness |
| `runtime.status` | 런타임이 알린 진행 상태 그대로(requesting …) | cc_stream(`system/status`) | liveness |
| `input.removed` | 줄에 선 입력을 런타임이 뺌(까닭 그대로: absorbed_mid_turn …) -- 그 입력은 새 차례를 열지 않는다 | cc_jsonl(`queue-operation remove`) | liveness |
| `runtime.compaction` | 런타임이 맥락을 압축함 -- trigger(auto · manual) · 전후 토큰 · 걸린 시간 | cc_jsonl(`compact_boundary.compactMetadata`) · cc_stream(SDK 꼴 `compact_metadata`, 실기록 미확인) | context · action_outcome |
| `dependency.probe` | 의존 대상 탐침 -- 상태 코드 · 오류 코드 · 경과 | Recorder | **dependency**(새) |
| `action.dispatch` · `action.result` | 실행기가 **실제로 실행한** 행동과 그 결과. 결정과는 `decision_ref`(id)로만 잇는다 | Recorder | **action_outcome**(새) |

앞으로 더할 liveness · recovery · dependency · action_outcome 도 같은 길(L0 → L1 → L2)을 지난다. 그 L1 팩은 아직 없다.

## 5. 예 -- 같은 관측, 다른 해석

**LLM 호출.** L0 는 `llm.response {input_tokens: 1200, output_tokens: 430, elapsed_ms: 1840, status_code: 200}` 까지다.
`token_state = NORMAL` · `execution_state = SUCCESS` · `latency_state = UNKNOWN`(SLO 가 없으니) 은 L1 이 만든다.

**시간 초과.** L0 는 `tool.start` · `tool.end {elapsed_ms: 31200}` 까지다. `timed_out` 은 실행기가 스스로 끊었다고 **선언**했을 때만
값이 있고, 아니면 '못 봄' 이다. L1 이 `timeout_threshold = 30000` 으로 `timeout_observed` 를 만든다. 문턱을 60 s 로 바꿔도 원장은
바이트 그대로 다시 읽힌다 -- `tests/test_boundary.py::TimeoutIsASensorQuestion` 가 이것을 그대로 시험한다.

**재시도.** L0 는 `llm.request {attempt: 3}` · `llm.error {error_code: DEADLINE_EXCEEDED, http_status: 504}` 까지다.
`recovery_state = RETRYING` · `provider_state = WARNING` 은 L1 이다. (google.rpc: DEADLINE_EXCEEDED 는 "may be returned even if the
operation has completed successfully" -- 그래서 L0 는 '실패' 라고 적지 않는다.)

## 6. L0 에 넣지 않는 것

| 넣지 않는 것 | 까닭 | 어디로 |
|---|---|---|
| `"health": "BAD"` · `token_state` · `latency_ok` | 해석 | L1 Sensor |
| `"risk": 0.82` · `quality_score` | 해석(점수) | L1 · L2 |
| `"should_retry": true` · `"policy": "RETURN"` · `"decision": "STOP"` | 정책 · 결정 | L4. 실행됐다면 그 사실만 `action.dispatch` 로 |
| 단가표로 계산한 비용 | 해석(단가 가정) | L1 cost 팩. L0 는 **원천이 보고한** `cost_usd` 만 |
| 백분위 · 이동 평균 · 비율 | 집계 | L1 |
| 결정의 까닭 · 프롬프트 · 맥락 | 결정 기록 | L4 의 결정 기록(CR decision record). L0 는 `decision_ref` 만 |

## 7. 지금 저장소들의 경계 점검 (2026-10-02)

처음 점검 때는 코드를 고치지 않았다. 사용자가 9 절의 1 · 2 · 3 을 정했고(2026-10-02) 아래 '처리' 칸이 그 결과다.

| 어디 | 무엇 | 판정 | 옮길 자리 · 처리 |
|---|---|---|---|
| Sensor `llmsensor/telemetry/collect.py` · `schema.py`(꼴 v3) | 원천 → 레코드 | **L0 맞음** | **필수 의존으로 바꾸고 Sensor 수집기를 지웠다(CMD-T9 · BD-62)**: `collect.py` 는 같은 이름 · 서명의 이음매(L0 사건 → 꼴 v3), 지우기 전 출력은 `tests/golden/` · 장부 `v3_digest` 로 얼렸다 |
| Sensor `llmsensor/telemetry/derive.py` | `token_burst`(중앙값 × 4) · `token_stagnation`(\|Δ\| < 1 %) · `token_oscillation` | **L1.** 문턱 있는 해석이 텔레메트리 패키지 안에 있었다 | **옮겼다**: Sensor `sensing/token/events.py`. 실데이터 9538 호출에서 출력 지문 불변(Sensor `tests/test_layer.py`) |
| Sensor `llmsensor/telemetry/derive.py` | `cache_hit_ratio` · `call_span_ms` · `tool_error_rate` | 집계 -- L1 | Sensor `sensing` |
| Sensor `sensing/execution` 의 `tool.timed_out` (Basis RUNTIME_DECLARED) | 런타임 선언 | L0 의 `declared` 와 같은 뜻 -- 맞음 | 그대로 |
| Sensor `sensing/cost` (단가표 × 토큰) | 계산 비용 | L1 맞음 | 그대로 |
| MS `run_telemetry.RunRecord.policy` (context_policy · prompt_policy · arbiter_decision · **정책이 본 state**) | 결정 · 상태가 텔레메트리 기록 안에 | **L0 위반이었다** | **뗐다**: MS `ms/decision_record.py` 의 DecisionRecord(id = 내용 sha256). RunRecord 는 `decision_ref` 만(ms-run-telemetry-3). 원장에 결정 줄이 먼저, 실행 줄이 id 로 가리킨다. L0 `action.dispatch.decision_ref` 도 그 id 를 쓴다 |
| MS `RunRecord.cost.source = "가격표"` · `tokens.context_tokens` · `retrieved_tokens`(추정) | 계산 · 추정 | L1 | 원천 보고 비용만 L0 에 |
| MS `RunRecord.interaction.retries` ("DENY 나 못 읽은 제안 때문에") | 까닭이 붙은 수 | 수는 사실이지만 까닭 분류는 해석 | L0: `llm.request.attempt` · `action.*`, 분류는 L1 |
| MS `RunRecord.outcome.task_success` | 평가자 라벨 | 바깥 관측 -- 사실이지만 런타임 관측이 아니다 | 앞으로 따로 사건 종류(평가 라벨)로. 지금 L0 에 없다 |
| MS `telemetry.Telemetry(source, entity, signal, value)` | 신호 꼴 | L0 와 맞는다(뜻 없음). `entity` 는 '주장' | L0 사건을 신호로 펴는 어댑터를 둘 수 있다(아직 없음) |

## 8. Sensor 와 어떻게 붙나

```
원천 ─► telemetry.collect / Recorder ─► L0 원장(JSONL) ─► telemetry.compat.to_sensor_records ─► llmsensor.state.normalize ─► State
```

`compat` 은 llmsensor 를 import 하지 않는다. 꼴 v3 의 칸 순서를 그대로 들고 있다. Sensor 의 옛 수집기는 지웠고(CMD-T9), 그 출력은
`tests/golden/*.json` 에 얼려 두었다 -- `tests/test_collect.py::GoldenEquivalence` 가 L0 → compat 출력을 그것과 맞댄다. 옆에 `../Sensor` 가 있으면
Sensor 이음매 · 꼴 v4 · State 정규화까지 확인한다(`SensorSitsOnL0`).
v3 에 자리가 없는 L0 칸(response_id · status_code · elapsed_ms · exit_code · llm.request · llm.error · heartbeat · action.* …)은
버린다 -- v3 를 넓히지 않는다. 그 칸들은 원장에 남아 있고, 새 L1 팩이 원장을 직접 읽을 때 쓰인다.

## 9. 정한 것 · 남은 것

| # | 물음 | 결정 (2026-10-02) | 상태 |
|---|---|---|---|
| 1 | Sensor → Telemetry 의존 | 선택 의존으로 시작 → BD-50 충족 뒤 **필수**(CMD-T9) | 됨 |
| 2 | Sensor `derive.py` 의 문턱 있는 파생 | **sensing/token 으로 옮김** | 됨 -- 정의 불변 |
| 3 | MS `RunRecord.policy` | **결정 기록으로 떼고 `decision_ref` 로 잇기** | 됨 |
| 4 | MS 가 Recorder 로 L0 를 직접 내기 | 붙임(선택 의존) -- `ms/l0.py` · `Runtime(l0_ledger=…)` · `ms ask --l0-ledger` | 됨 -- 모형 호출 · 도구 호출 · 실행 시작/끝(+`decision_ref`). `action.*` 은 Action Executor 가 서면 |
| 5 | 새 L1 팩: liveness · recovery · dependency · action_outcome | **Sensor 세션 소유**(baseline BD-45). 이 세션은 L0 사건 이름 · 칸만 정한다 -- 차례 경계 사건(BD-47, CMD-T2) | L0 쪽 됨 |
| 6 | Sensor 를 필수 의존으로(Sensor 의 `telemetry/collect.py` 삭제) | BD-50 충족(BD-62) -> CMD-T9 | **됨** -- 이음매 · 필수 의존 · 없으면 분명한 ImportError. 원래 수집기 없는 대조는 아래 '대조를 대신하는 것' |

## 10. 잰 것 · 모르는 것

- **대조를 대신하는 것(CMD-T9 뒤)** -- 비교할 '원래 수집기' 가 없어졌으므로 셋으로 나눈다:
  1. **얼린 출력**: 지우기 직전 Sensor 수집기(Sensor `f6f02fc`)의 출력. 시험 고정 자료는 `tests/golden/*.json` 그대로(`GoldenEquivalence`),
     실기록은 장부 `v3_digest`(고정 열쇠 지문) -- `python3 eval/l0_check.py --verify <source> <파일>`. 얼린 실기록: sweagent 7 · cc_stream 3 · cc_jsonl 2.
  2. **불변식**(새 실기록에 쓴다): Sensor `l0.compare` / `python3 -m llmsensor l0-check` 가 이제 꼴 v4 통과 · 결정성 · State 정규화를 본다(`against: "invariants"`).
  3. **변이**: `eval/mutation.py` 37/37 -- 얼린 출력과 달라지게 하는 변경(칸 순서 바꾸기 포함)은 시험이 잡는다.

- **수집기 결함 D1–D4 고침(CMD-T6, Sensor `docs/MS_HEALTH_INVENTORY.md` §1)** -- L0 수집기와 Sensor 수집기(`llmsensor/telemetry/collect.py`)를 같은 규칙으로:
  - D1 시간 초과: 구조화 칸 `timedOutAfterMs` 먼저. 글 문구는 오류 결과이고 'Exit code' 로 시작할 때만(성공 출력의 인용은 아니다).
  - D2 429: 런타임이 끼운 API 오류 줄(`isApiErrorMessage` · `apiErrorStatus`, 모델 `<synthetic>`)은 모형 호출이 **아니다** -- `llm.error` +
    `provider.rate_limit`(`quotaLimits`). 꼴 v3 에서는 실행 요약의 `api_error_status` · `rate_limit_status`. 그 밖의 `<synthetic>` 줄도 모형 호출이 아니다.
  - D3: D2 의 결과로 단가표에 없는 '모델' 이 세션 비용을 None 으로 만들지 않는다.
  - D4: `compact_boundary` -> `runtime.compaction`.
  - 합성 세션에서 Sensor State 가 `rate_limit_state = LIMITED` · `runtime_reliability = FAILURE_OBSERVED` 로 읽는다(전에는 UNKNOWN · NO_FAILURE_OBSERVED).
  - **실데이터(이 세션 JSONL)**: 도구 시간 한도를 넘긴 실제 명령 하나(Bash 도구 timeout 5 s, 일부러) -> 런타임이 죽이지 않고 백그라운드로 옮겼다.
    L0 `tool.end`: `timed_out=True` · `declared_timeout_ms=5000` · `moved_to_background=True` · `is_error=False`(옛 글 규칙이면 거짓 음성).
    같은 기록에 `input.removed`(absorbed_mid_turn) 1. 429 · 압축은 이 세션에 없었다 -- 합성 자료로만 시험했다.

- **차례 경계(CMD-T2) 실데이터**: 이 세션 JSONL 에서 `input.received` 7 · `turn.start` 6 · `turn.end` 5(여섯째 차례는 수집 시점에 열려 있었고,
  일곱째 입력은 차례 중에 줄에 선 알림이다). JSONL 의 `turn.end` 는 **Stop 훅이 있어야** 나온다(그 요약 줄뿐이다) -- 훅이 없는 세션에서는 차례 끝을 못 본다.
  `source.closed` 는 캡처가 닫힘 줄을 적어야 나온다(이 저장소 `eval/capture_stream.py` 가 적는다).
  cc_stream 실데이터(CMD-T8, 사용자 허락 · `claude -p` 세 번, haiku, 보고 비용 합 $0.0889): 세 기록 모두 `turn.start` 1 · `turn.end` 1 ·
  `run.end` 1 · `source.closed` 1, `l0-check` 같음(2/2 · 4/4 · 4/4). 캡처 글은 커밋하지 않았다. 같은 실행의 자식 JSONL 셋도 같음 --
  그러나 Stop 훅이 없어 `turn.end` 가 없다(위 한계 그대로).

- 시험 33 개 통과. **변이 17 가지 모두 빨강**(`python3 eval/mutation.py`, 결과 `eval/mutation_results.json`) -- 해석 칸 넣기 · 우리 문턱 넣기 ·
  경과 시간으로 시간 초과 판정 · 결과 없음을 성공으로 · 예외 메시지 남김 · 오지 않은 결과 지어내기 · 보고된 null 을 못 봄으로 · 경로 평문 ·
  0 을 못 봄으로 · 봉투 열기 · 위층 import …
- **실데이터 한 번**: 이 작업을 한 Claude Code 세션 자신의 JSONL(모형 호출 27 · 도구 35)에서 Sensor 수집기 출력과 `compat` 출력이
  **62/62 레코드 같았다.** 그 파일은 커밋하지 않았다(사적 글). cost-state 줄은 그 파일에 없었다 -- run.snapshot 은 합성 자료로만 시험했다.
  도구 35 개 중 끝 사건은 34 개 -- 수집 시점에 돌던 도구 하나가 '시작만 있음' 으로 남았다(규칙 7 그대로).
- Recorder 는 MS 런타임에 붙었다(모의 provider · 시험으로만 돌려 봤다. 진짜 API 로는 아직).
- OpenAI · Gemini usage 대응은 SDK 소스로만 확인했다(확인수준 D, Sensor 와 같음). OpenAI 오류는 429 만 번역한다.
- `compat` 이 Sensor 와 다를 수 있는 경우 하나: 한 stream 에 `autocompact_state` 가 둘 이상이고 마지막 것에 threshold 가 없으면,
  Sensor 는 None 으로 덮고 `compat` 은 앞의 값을 쓴다. 실데이터에서 본 적은 없다.
- reported 와 declared 의 갈림이 L1 에서 쓸모가 있는지는 재지 않았다 -- 설계 선택이다.
