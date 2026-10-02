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

## 4. 사건 목록 (`telemetry/catalog.py`)

| 사건 | 무엇 | 지금 내는 곳 | L1 에서 읽을 팩 |
|---|---|---|---|
| `llm.request` | 모형에 보냄(몇 번째 시도인가) | Recorder | execution · recovery |
| `llm.response` | 응답 하나 -- 토큰(캐시 밖 · 읽기 · 쓰기 5m/1h · 출력 · 생각) · 끝난 까닭 · HTTP 상태 · 시각 · 경과 | 세 수집기 · Recorder | token · latency · cost · provider |
| `llm.error` | 공급자 오류 -- HTTP 상태 · 공급자 코드(원래 값) · 정준 코드(번역) · 선언된 대기 | Recorder | provider · recovery |
| `tool.start` · `tool.end` | 도구 호출과 결과 -- 오류 깃발 · 중단 · 선언된 시간 초과 · 종료 코드 · 예외 종류 · 출력 길이 · 경과 | 세 수집기 · Recorder | execution · latency · liveness |
| `run.start` · `run.end` | 실행 시작 · 끝 요약(런타임이 준 값만. 합계를 우리가 내지 않는다) | cc_stream · sweagent · Recorder | execution · cost |
| `run.snapshot` | 실행 도중의 누적 스냅숏(Claude Code cost-state -- 끝이 아니다) | cc_jsonl | cost |
| `runtime.limits` | 런타임이 선언한 맥락 창 · 최대 출력 · 자동 압축 문턱 | cc_stream | token |
| `provider.rate_limit` | 사용률 · 런타임 상태 문자열 · 런타임 문턱 -- **사건마다** 따로(마지막 값으로 덮지 않는다) | cc_stream | provider |
| `heartbeat` | 살아 있다는 박동(emitter 마다 번호) | Recorder | **liveness**(새) |
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

코드는 **고치지 않았다**. 옮길 자리만 적는다 -- 옮길지는 사용자 결정이다(9 절).

| 어디 | 무엇 | 판정 | 옮길 자리 |
|---|---|---|---|
| Sensor `llmsensor/telemetry/collect.py` · `schema.py`(꼴 v3) | 원천 → 레코드 | **L0 맞음.** 이 저장소의 `collect` 가 그것을 그대로 옮겼고, `compat` 으로 되지은 v3 가 **같다**(시험) | 이 저장소로 일원화 |
| Sensor `llmsensor/telemetry/derive.py` | `token_burst`(중앙값 × 4) · `token_stagnation`(\|Δ\| < 1 %) · `token_oscillation` | **L1.** 문턱 있는 해석이 텔레메트리 패키지 안에 있다 | Sensor `sensing/token` |
| Sensor `llmsensor/telemetry/derive.py` | `cache_hit_ratio` · `call_span_ms` · `tool_error_rate` | 집계 -- L1 | Sensor `sensing` |
| Sensor `sensing/execution` 의 `tool.timed_out` (Basis RUNTIME_DECLARED) | 런타임 선언 | L0 의 `declared` 와 같은 뜻 -- 맞음 | 그대로 |
| Sensor `sensing/cost` (단가표 × 토큰) | 계산 비용 | L1 맞음 | 그대로 |
| MS `run_telemetry.RunRecord.policy` (context_policy · prompt_policy · arbiter_decision · **정책이 본 state**) | 결정 · 상태가 텔레메트리 기록 안에 | **L0 위반.** `to_signals` 가 이미 신호로 안 펴지만, 기록 자체에 섞여 있다 | CR 결정 기록 / Policy 기록. L0 에는 `action.dispatch.decision_ref` |
| MS `RunRecord.cost.source = "가격표"` · `tokens.context_tokens` · `retrieved_tokens`(추정) | 계산 · 추정 | L1 | 원천 보고 비용만 L0 에 |
| MS `RunRecord.interaction.retries` ("DENY 나 못 읽은 제안 때문에") | 까닭이 붙은 수 | 수는 사실이지만 까닭 분류는 해석 | L0: `llm.request.attempt` · `action.*`, 분류는 L1 |
| MS `RunRecord.outcome.task_success` | 평가자 라벨 | 바깥 관측 -- 사실이지만 런타임 관측이 아니다 | 앞으로 따로 사건 종류(평가 라벨)로. 지금 L0 에 없다 |
| MS `telemetry.Telemetry(source, entity, signal, value)` | 신호 꼴 | L0 와 맞는다(뜻 없음). `entity` 는 '주장' | L0 사건을 신호로 펴는 어댑터를 둘 수 있다(아직 없음) |

## 8. Sensor 와 어떻게 붙나

```
원천 ─► telemetry.collect / Recorder ─► L0 원장(JSONL) ─► telemetry.compat.to_sensor_records ─► llmsensor.state.normalize ─► State
```

`compat` 은 llmsensor 를 import 하지 않는다. 꼴 v3 의 칸 순서를 그대로 들고 있고, 옆에 `../Sensor` 가 있으면 시험이 Sensor 수집기의 출력과
**같음**을 확인한다(`tests/test_collect.py::SensorEquivalence` -- 세 원천 + State 정규화 묶음까지).
v3 에 자리가 없는 L0 칸(response_id · status_code · elapsed_ms · exit_code · llm.request · llm.error · heartbeat · action.* …)은
버린다 -- v3 를 넓히지 않는다. 그 칸들은 원장에 남아 있고, 새 L1 팩이 원장을 직접 읽을 때 쓰인다.

## 9. 다음 -- 사용자 결정이 필요한 것

| # | 물음 | 선택지 | 제안 |
|---|---|---|---|
| 1 | Sensor → Telemetry 의존 | (a) 선택 의존(`pip install git+…/Telemetry`, 없으면 지금 수집기) · (b) 필수 의존, Sensor 의 `telemetry/collect.py` 삭제 | (a) 로 시작해 v3 대조가 실데이터에서 계속 같으면 (b) |
| 2 | Sensor `derive.py` 의 문턱 있는 파생 | sensing/token 으로 옮김 | 옮김 -- 뜻 불변 시험과 함께 |
| 3 | MS `RunRecord.policy` | (a) 그대로 두고 문서로만 표시 · (b) 결정 기록으로 떼고 `decision_ref` 로 잇기 | (b) -- 계획 ⑤ Policy 와 같이 |
| 4 | MS 가 Recorder 로 L0 를 직접 내기 | 계획 ②③ 사이 | Sensor 배선(②)과 같이 |
| 5 | 새 L1 팩: liveness · recovery · dependency · action_outcome | L0 사건은 준비됨 | 문턱은 운영자 설정만(Sensor 의 규율) |

## 10. 잰 것 · 모르는 것

- 시험 33 개 통과. **변이 17 가지 모두 빨강**(`python3 eval/mutation.py`, 결과 `eval/mutation_results.json`) -- 해석 칸 넣기 · 우리 문턱 넣기 ·
  경과 시간으로 시간 초과 판정 · 결과 없음을 성공으로 · 예외 메시지 남김 · 오지 않은 결과 지어내기 · 보고된 null 을 못 봄으로 · 경로 평문 ·
  0 을 못 봄으로 · 봉투 열기 · 위층 import …
- **실데이터 한 번**: 이 작업을 한 Claude Code 세션 자신의 JSONL(모형 호출 27 · 도구 35)에서 Sensor 수집기 출력과 `compat` 출력이
  **62/62 레코드 같았다.** 그 파일은 커밋하지 않았다(사적 글). cost-state 줄은 그 파일에 없었다 -- run.snapshot 은 합성 자료로만 시험했다.
  도구 35 개 중 끝 사건은 34 개 -- 수집 시점에 돌던 도구 하나가 '시작만 있음' 으로 남았다(규칙 7 그대로).
- **Recorder 는 아직 아무 런타임에도 안 붙었다.** 시험만 있다.
- OpenAI · Gemini usage 대응은 SDK 소스로만 확인했다(확인수준 D, Sensor 와 같음). OpenAI 오류는 429 만 번역한다.
- `compat` 이 Sensor 와 다를 수 있는 경우 하나: 한 stream 에 `autocompact_state` 가 둘 이상이고 마지막 것에 threshold 가 없으면,
  Sensor 는 None 으로 덮고 `compat` 은 앞의 값을 쓴다. 실데이터에서 본 적은 없다.
- reported 와 declared 의 갈림이 L1 에서 쓸모가 있는지는 재지 않았다 -- 설계 선택이다.
