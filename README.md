# Telemetry — L0: "무슨 일이 일어났나"

**Telemetry 는 판단하지 않고 관측 사실을 기록한다.** Sensor(L1)가 그 사실을 상태 관측으로 바꾼다. 이 저장소는 별개의 시스템이 아니라
**Sensor 의 가장 아래 관측 층을 독립시킨 것**이다. 표준 라이브러리만 쓰고, 위층(llmsensor · ms · dc)을 import 하지 않는다.

```
실제 실행 / Provider / Tool
        │
L0  Telemetry   무슨 일이 일어났나              ← 이 저장소
L1  Sensor      그 관측이 무엇을 뜻하나          Sensor
L2  State       지금 시스템이 어떤 상태인가       Sensor · MS
L3  DC          이번 결정에 무엇이 필요한가       DC
L4  Policy      그래서 무엇을 할 것인가           MS
L5  Action      ─────────────► 결과는 다시 L0 로 (닫힌 고리)
```

설계 전체: **[`docs/TELEMETRY.md`](docs/TELEMETRY.md)** · 선행조사: [`paper/선행조사/Telemetry.md`](paper/선행조사/Telemetry.md)

## Telemetry ≠ Sensor

| L0 에 적는다 (관측) | L0 에 적지 않는다 (해석 · 정책) |
|---|---|
| `input_tokens=1200` · `output_tokens=430` · `elapsed_ms=1840` · `status_code=200` | `token_state=NORMAL` · `execution_state=SUCCESS` |
| `tool.start` · `tool.end {elapsed_ms: 31200}` | `TIMEOUT` (문턱 30 s 는 Sensor 의 설정) |
| `attempt=3` · `error_code=DEADLINE_EXCEEDED` (원래 값 504 와 함께) | `recovery_state=RETRYING` · `should_retry` |
| 실행기가 실제로 실행한 행동 `action.dispatch {action_type, decision_ref}` | `"policy": "RETURN"` · `"decision": "STOP"` · 결정의 까닭 |

칸마다 출처 종류가 붙는다: `reported`(원천이 준 수) · `declared`(원천이 스스로 붙인 분류 · 상태 · 한도) · `measured`(수집기가 잰 시계 ·
개수) · `translated`(출처 있는 대응표로 어휘만) · `ref`(id). 해석 어휘(health · risk · should · state · score · decision …)는 칸 이름에
쓸 수 없고, 문턱 · 한도 낱말은 원천이 **선언한** 칸에만 쓸 수 있다 -- 시험이 붙든다.

## 쓰기

```python
from telemetry import Recorder, JsonlSink
from telemetry.collect import from_cc_jsonl, from_cc_stream, from_sweagent
from telemetry.compat import to_sensor_records
from telemetry import ledger

# 1) 로그 원천에서
events = from_cc_jsonl("~/.claude/projects/<프로젝트>/<세션>.jsonl", run_id="s1")

# 2) 프로세스 안에서 (MS 런타임 · 도구 실행기 · 행동 실행기)
rec = Recorder("r17", JsonlSink("ledger.jsonl"), source="inproc:ms")
rec.llm_response(0, "anthropic", usage=resp_usage, status_code=200, elapsed_ms=1840)
with rec.tool("Bash", {"command": "pytest -q"}) as t:          # tool.start → tool.end (경과 시간은 단조 시계)
    p = run(...)
    t.result(exit_code=p.returncode, is_error=p.returncode != 0, output=p.stdout)
with rec.action("RETURN", decision_ref=dc_id) as a:            # 결과가 다시 L0 로
    a.result(status_code=200)
rec.heartbeat("worker-1")

# 3) Sensor 가 그대로 앉는다 -- 꼴 v3 레코드로 되짓기
records = to_sensor_records(ledger.read("ledger.jsonl"))       # -> llmsensor.state.normalize.from_telemetry
```

```bash
python3 -m unittest discover -s tests -t .    # 33 개. 옆에 ../Sensor 가 있으면 Sensor 수집기와의 대조까지
python3 eval/mutation.py                      # 변이 17 가지 -- 모두 빨개져야 한다
```

## 알고 쓸 것

- 수집기 셋은 Sensor 의 수집기(꼴 v3)를 옮긴 것이다. 같은 원천에서 `compat` 이 되지은 레코드는 Sensor 의 것과 **같다**(시험 · 실데이터 한 세션).
- Sensor 는 이 저장소를 **선택 의존**으로 쓴다(`llmsensor.telemetry.l0` · `pip install "llmsensor[l0]"`). 없으면 Sensor 수집기로 돈다.
- MS 는 결정 기록을 텔레메트리에서 뗐다(`RunRecord.decision_ref` → `DecisionRecord.id`). MS 런타임은 Recorder 로 L0 를 직접 낸다(`Runtime(l0_ledger=…)` · `ms ask --l0-ledger`).
- liveness · recovery · dependency · action_outcome 의 **L0 사건은 있다**(heartbeat · llm.request.attempt · dependency.probe · action.*).
  그것을 읽는 L1 팩은 아직 없다.
