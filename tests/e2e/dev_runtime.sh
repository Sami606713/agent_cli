#!/usr/bin/env bash
# End-to-end check of `agentctl dev`:
#   health gate → same-origin proxy → thread creation → clean teardown.
set -u
PROJECT="${AGENTCTL_E2E_PROJECT:?set AGENTCTL_E2E_PROJECT to a scaffolded project dir}"
# Override if agentctl is not on PATH (e.g. AGENTCTL_BIN=/path/to/.venv/bin/agentctl).
AGENTCTL="${AGENTCTL_BIN:-agentctl}"
cd "$PROJECT"

echo "ANTHROPIC_API_KEY=sk-ant-dummy-for-e2e" >> .env

LOG=/tmp/agentctl-dev.log
"$AGENTCTL" dev --no-open --strict-port > "$LOG" 2>&1 &
DEV_PID=$!
echo "dev pid=$DEV_PID"

pass=0; fail=0
check() { # name, condition-output, expected-substring
  if [[ "$2" == *"$3"* ]]; then echo "  PASS  $1"; pass=$((pass+1));
  else echo "  FAIL  $1"; echo "        got: ${2:0:200}"; fail=$((fail+1)); fi
}

# Wait for the frontend, which only starts after the agent passed its health gate.
for i in $(seq 1 120); do
  curl -sf -o /dev/null http://127.0.0.1:3000/ && break
  kill -0 $DEV_PID 2>/dev/null || { echo "dev exited early"; cat "$LOG"; exit 1; }
  sleep 1
done

echo "--- checks"
check "agent /ok direct"        "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:2024/ok)" "200"
check "frontend serves"         "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/)" "200"
check "proxy GET /ok"           "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/api/agent/ok)" "200"
check "proxy GET /info"         "$(curl -s http://127.0.0.1:3000/api/agent/info)" "version"
check "proxy POST creates thread" \
  "$(curl -s -X POST http://127.0.0.1:3000/api/agent/threads -H 'content-type: application/json' -d '{}')" \
  "thread_id"
check "proxy lists assistants" \
  "$(curl -s -X POST http://127.0.0.1:3000/api/agent/assistants/search -H 'content-type: application/json' -d '{}')" \
  "assistant_id"
check "no api key in client bundle" \
  "$(curl -s http://127.0.0.1:3000/ | grep -c 'sk-ant-dummy' || true)" "0"

echo "--- teardown (SIGINT, as Ctrl-C would)"
kill -INT $DEV_PID
for i in $(seq 1 30); do kill -0 $DEV_PID 2>/dev/null || break; sleep 0.5; done

sleep 1
LEFT_2024=$(ss -ltn "sport = :2024" 2>/dev/null | tail -n +2 | wc -l)
LEFT_3000=$(ss -ltn "sport = :3000" 2>/dev/null | tail -n +2 | wc -l)
check "port 2024 released" "$LEFT_2024" "0"
check "port 3000 released" "$LEFT_3000" "0"
ORPHANS=$(pgrep -f "langgraph dev|next-server|next dev" | wc -l)
check "no orphaned processes" "$ORPHANS" "0"

echo "--- result: $pass passed, $fail failed"
[[ $fail -eq 0 ]] || { echo "--- dev log tail"; tail -40 "$LOG"; }
exit $fail
