"""stream-json 캡처 -- 명령의 표준 출력을 줄마다 {"_t": 수집기 단조 ms, "line": {...}} 로 적고, 프로세스가 끝나면
마지막에 {"_t": ms, "closed": true, "returncode": n} 한 줄을 더한다(L0 `source.closed` 의 원천).

    python3 eval/capture_stream.py <out.stream.jsonl> --cwd <작업 디렉터리> [--clean-env] -- claude -p "..." --output-format stream-json ...

꼴은 Sensor `eval/run_claude.py` 와 같다(JSON 이 아닌 줄은 {"_t", "raw"}). 닫힘 줄만 더했다(baseline CMD-T8 이 허락한 이 세션 소유 도구).
--clean-env: 부모 Claude Code 세션에 묶인 환경 변수(세션 id · 원격 ingress · 메시징)를 빼고 돌린다 -- 자식 실행이 부모 세션에 쓰지 않게.
**캡처 내용(대화 글)은 커밋하지 않는다.** 장부에는 해시 · 수 · 같은가만(eval/l0_check.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

# 부모 세션에 묶인 것만 뺀다. 인증 경로(ANTHROPIC_BASE_URL · CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST 등)는 그대로 둔다
PARENT_BOUND = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID", "SESSION_INGRESS_URL",
                "CLAUDE_SESSION_INGRESS_TOKEN_FILE", "CLAUDE_CODE_POST_FOR_SESSION_INGRESS_V2", "CLAUDE_CODE_TEE_SDK_STDOUT",
                "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SYNC_SESSION_REFS",
                "CLAUDE_CODE_REMOTE_SEND_KEEPALIVES", "CLAUDE_PID", "CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION",
                "CLAUDE_CODE_DIAGNOSTICS_FILE", "CLAUDE_CODE_WORKER_EPOCH")


def main(argv) -> int:
    if "--" not in argv or len(argv) < 3:
        print(__doc__)
        return 2
    i = argv.index("--")
    opts, cmd = argv[:i], argv[i + 1:]
    out = opts[0]
    cwd = opts[opts.index("--cwd") + 1] if "--cwd" in opts else os.getcwd()
    env = dict(os.environ)
    if "--clean-env" in opts:
        for k in PARENT_BOUND:
            env.pop(k, None)
    os.makedirs(cwd, exist_ok=True)
    t0 = time.monotonic()
    with open(out, "w", encoding="utf-8") as f, open(out + ".stderr", "w", encoding="utf-8") as err:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL,
                             text=True)
        for line in p.stdout:
            t = round((time.monotonic() - t0) * 1000, 3)
            try:
                row = {"_t": t, "line": json.loads(line)}
            except json.JSONDecodeError:
                row = {"_t": t, "raw": line.rstrip("\n")}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
        rc = p.wait()
        f.write(json.dumps({"_t": round((time.monotonic() - t0) * 1000, 3), "closed": True, "returncode": rc}) + "\n")
    print(json.dumps({"out": out, "returncode": rc, "seconds": round(time.monotonic() - t0, 1)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
