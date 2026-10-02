# 선행조사 -- Telemetry 를 Sensor 아래의 독립 관측 층(L0)으로 (2026-10-02)

코드보다 먼저 커밋한다. 물음은 하나다: **"무슨 일이 일어났나" 를 적는 층과 "그것이 무엇을 뜻하나" 를 정하는 층을 가르는 선례가 있나,
있다면 그 경계는 어디에 그어졌나.** 이 환경에서 prometheus.io 는 막혔고(egress), 같은 문서의 GitHub 원문을 읽었다.

## 읽은 것

| 자료 | 확인수준 | 읽은 문장 | 빌린 설계 결정 |
|---|---|---|---|
| **CloudEvents** spec -- cloudevents/spec `cloudevents/spec.md` | [출처:전문] | 필수 속성 `id` · `source` · `specversion` · `type`. "Producers MUST ensure that `source` + `id` is unique for each distinct event." `type` 은 "a value describing the type of event related to the originating occurrence". 선택 속성 `time` · `subject` · `dataschema` | 사건 봉투를 **사건의 종류(type)** · 낸 곳(source) · 판본(spec) · 유일 id 로 짓는다. `type` 은 **일어난 일**(occurrence)을 말한다 -- 그 일의 평가가 아니다. 우리: `spec` · `id = run_id:seq` · `source` · `type` · `at` |
| **OpenTelemetry GenAI** semantic conventions -- open-telemetry/semantic-conventions-genai `gen-ai-spans.md` | [출처:전문 -- 해당 절] | `gen_ai.usage.input_tokens` "SHOULD include all types of input tokens, including cached tokens", `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_write.input_tokens`, `gen_ai.response.id`, `gen_ai.response.finish_reasons`, `error.type`("a class of error the operation ended with", Stable). 토큰 칸은 모두 **Development** | 토큰 · 캐시 읽기 · 캐시 쓰기 · 끝난 까닭 · 오류 **종류**는 관측 칸이다(해석 칸이 아니다). 다만 OTel 의 input 은 캐시를 **포함**하고 Anthropic 은 **뺀다** -- 우리는 가장 잘게 쪼갠 꼴(캐시 밖 · 읽기 · 쓰기)로 적고 OTel 합계는 내보낼 때 더한다(되돌릴 수 있는 쪽). Development 라 이름은 바뀔 수 있다 -- 내보내기 표 한 곳에만 둔다 |
| **Prometheus** instrumentation practices -- prometheus/docs `docs/practices/instrumentation.md` | [출처:전문 -- 해당 절] | "Timestamps, not time since": "export the Unix timestamp at which it happened - not the time since it happened." "Failures": 실패마다 카운터를 올리고 "some other metric representing the total number of attempts". 원 카운터는 서버에서 `rate()` 로 | **수집 쪽은 원 사실(시각 · 횟수 · 시도 수)을 내고, 비율 · 창 · 문턱은 위에서.** 우리: 사건에는 시각과 관측값만, `elapsed > 30 s` 같은 비교는 Sensor 에. 실패만이 아니라 **시도**도 적는다(`llm.request` · `tool.start` -- 끝 사건이 없는 시작이 곧 '끝나지 않음' 의 증거가 된다) |
| Google **google.rpc.Code** -- googleapis `code.proto` | [출처:전문 -- 앞 조사 `Sensor/paper/선행조사/MS센싱.md` 에서 읽음] | `DEADLINE_EXCEEDED` "may be returned even if the operation has completed successfully" | 오류 코드를 정준 이름으로 **옮기는 것**은 출처 있는 어휘 대응(번역)이지 판단이 아니다 -- 그래서 L0 에 둘 수 있다. 단 원래 값(HTTP 상태 · 공급자 코드)을 함께 남기고, '실패했다' 고 적지 않는다 |
| NASA cFS **Limit Checker** README -- nasa/LC | [출처:전문 -- 앞 조사] | "monitors telemetry data points ... compares the values against predefined threshold limits" | 텔레메트리 점과 그것을 문턱에 비교하는 앱이 **다른 구성요소**다. 우리: L0(텔레메트리 점) · L1(Sensor, 문턱 비교) |
| Chow & Willsky 1984 analytical redundancy | [출처:기억 -- Sensor README 가 이미 인용] | 잔차 생성 → 결정의 두 단계 | 측정(L0)은 두 단계 어느 쪽에도 속하지 않는다. 잔차는 L1 |

## 못 읽은 것 -- 근거로 쓰지 않는다

- NASA **F´** 의 event(심각도가 붙은 이산 사건) 대 telemetry channel(값의 흐름) 구분 -- **[출처:기억]**. 두 문서(`03-port-comp-top.md` ·
  `ground-interface.md`)를 열었지만 그 정의가 없었다. F´ event 에는 심각도(WARNING_HI 등)가 붙는데, 이것은 **낸 쪽이 해석을 넣은 것**이라
  우리 L0 의 규율과 다르다 -- 그래서 인용해도 '반례' 로만 쓸 수 있다.
- Event Sourcing(Fowler) -- **[출처:기억]**. "사건 기록이 진실이고 상태는 그 사건들의 재생" 이라는 생각. 우리의 'State 는 L0 원장을 다시 읽어
  재현된다' 와 같은 방향이지만 원문을 안 읽었다.
- OTel Logs/Events data model 의 `SeverityNumber` -- 열지 않았다.

## 정리 -- 선례가 그은 경계

1. **사건 봉투는 일어난 일의 종류를 말한다**(CloudEvents `type`). 평가(BAD · RISK)를 종류 이름에 넣지 않는다.
2. **수집 쪽은 원 사실, 해석 · 문턱은 위에서**(Prometheus 시각 · 카운터, cFS LC). 같은 원장을 문턱만 바꿔 다시 읽을 수 있다.
3. **어휘 번역은 해석이 아니다** -- 출처 있는 대응표(google.rpc)일 때만, 원래 값을 남기고.
4. 반례: F´ event 의 심각도처럼 **낸 쪽이 해석을 넣는** 설계도 흔하다. 우리는 그 길을 막는다 -- 런타임 자신이 선언한 값(경고 상태 문자열 ·
   시간 초과 문구 · 끝난 까닭)은 **'선언(declared)' 으로 따로 표시해** 받되, 우리가 만든 판단은 넣지 않는다.

## 우리가 다른 점

새 방법이 아니다. 위 선례들의 경계를 **LLM 실행의 원천들**(Claude Code JSONL · claude -p stream-json · SWE-agent .traj · 프로세스 안 계측)에
적용하고, 그 경계를 **시험으로 붙든다**: 닫힌 꼴(모르는 칸 거절) · 칸 이름의 해석 어휘 금지 · 칸마다 출처 종류(reported · declared ·
measured · translated · ref) · L0 가 위층을 import 하지 않음.

## 아직 못 지운 가능성

- OTel GenAI 의 Events(`gen_ai.client.inference.operation.details` 등)가 이미 같은 일을 할 수 있다 -- 이번엔 spans 절만 읽었다.
  그래서 L0 꼴은 OTel 로 **내보낼 수 있게만** 하고, OTel 을 꼴의 원천으로 삼지 않는다(토큰 칸이 Development).
- 원천이 '선언' 한 값과 '보고' 한 값의 경계(예: `stop_reason` 은 보고인가 선언인가)는 판단이 들어간다. 우리는 **원천이 붙인 분류 · 상태 문자열 ·
  한도는 declared**, 수 · 시각은 reported 로 갈랐다. 이 갈림이 Sensor 에서 쓸모가 있는지는 재지 않았다.
