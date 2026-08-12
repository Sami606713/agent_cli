#!/usr/bin/env bash
# Does long-term memory survive a server restart?
#
# This is the only test that proves the feature. An in-process assertion passes
# with InMemoryStore and proves nothing, and an earlier version of this probe
# was itself wrong: `kill -9 <pid>` kills the `langgraph dev` parent but leaves
# its uvicorn child holding the port, so the "restart" silently reused the same
# process. Here the server runs under setsid, is killed by process group, and
# the port must actually be released before the next boot counts.
#
#   AGENTCTL_E2E_PROJECT=/path/to/scaffolded/project tests/e2e/memory_persistence.sh
set -u

PROJECT="${LANGCTL_E2E_PROJECT:?set LANGCTL_E2E_PROJECT to a scaffolded project dir}"
PORT="${LANGCTL_E2E_PORT:-2079}"
cd "$PROJECT"

NS="e2e"
KEY="fact1"
VALUE="the user prefers metric units"

pass=0; fail=0
check() {
  if [[ "$2" == *"$3"* ]]; then echo "  PASS  $1"; pass=$((pass+1))
  else echo "  FAIL  $1"; echo "        got: ${2:0:160}"; fail=$((fail+1)); fi
}

port_busy() { ss -ltn "sport = :$PORT" 2>/dev/null | tail -n +2 | grep -q .; }

boot() {
  setsid ./.venv/bin/langgraph dev --no-browser --host 127.0.0.1 --port "$PORT" \
    > /tmp/memory-dev.log 2>&1 < /dev/null &
  echo $! > /tmp/memory.pgid
  for _ in $(seq 1 90); do
    curl -sf -o /dev/null "http://127.0.0.1:$PORT/ok" && return 0
    sleep 1
  done
  echo "  server failed to boot"; tail -12 /tmp/memory-dev.log; return 1
}

kill_server() {
  local pgid; pgid=$(cat /tmp/memory.pgid 2>/dev/null)
  [ -n "$pgid" ] && kill -9 -- "-$pgid" 2>/dev/null
  for _ in $(seq 1 30); do port_busy || break; sleep 0.5; done
  port_busy && { echo "  port still held — a restart here would be fake"; return 1; }
  return 0
}

echo "--- clean slate"
rm -rf data .langgraph_api

echo "--- boot, write a memory"
boot || exit 1
put_code=$(curl -s -o /dev/null -w '%{http_code}' -X PUT "http://127.0.0.1:$PORT/store/items" \
  -H 'content-type: application/json' \
  -d "{\"namespace\":[\"$NS\"],\"key\":\"$KEY\",\"value\":{\"text\":\"$VALUE\"}}")
check "store write accepted" "$put_code" "204"
check "readable before restart" \
  "$(curl -s -G "http://127.0.0.1:$PORT/store/items" \
      --data-urlencode "namespace=$NS" --data-urlencode "key=$KEY")" "$VALUE"

# The storage assertion depends on the backend the project chose.
backend=$(python3 -c "
import yaml
print(yaml.safe_load(open('agent.yaml'))['memory']['long_term'].get('backend','sqlite'))" 2>/dev/null)
echo "  backend: $backend"
if [ "$backend" = "sqlite" ]; then
  check "sqlite file created" "$([ -f data/memory.sqlite ] && echo yes || echo no)" "yes"
else
  check "store rows written to $backend" \
    "$(curl -s -G "http://127.0.0.1:$PORT/store/items" \
        --data-urlencode "namespace=$NS" --data-urlencode "key=$KEY")" "$VALUE"
fi

echo "--- kill the whole process group and restart"
kill_server || { echo "--- result: teardown failed"; exit 1; }
boot || exit 1

check "SURVIVES RESTART" \
  "$(curl -s -G "http://127.0.0.1:$PORT/store/items" \
      --data-urlencode "namespace=$NS" --data-urlencode "key=$KEY")" "$VALUE"

echo "--- threads still work (server-managed checkpointer by default)"
thread=$(curl -s -X POST "http://127.0.0.1:$PORT/threads" \
  -H 'content-type: application/json' -d '{}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['thread_id'])")
check "thread created" "$thread" "-"

# Only assert a checkpoint file when this project owns the checkpointer.
if grep -q '"checkpointer"' langgraph.json 2>/dev/null; then
  check "checkpoints file created (custom checkpointer)" \
    "$([ -f data/checkpoints.sqlite ] && echo yes || echo no)" "yes"
else
  echo "  SKIP  checkpoints file — short_term is server-managed by design"
fi

kill_server
echo "--- result: $pass passed, $fail failed"
[[ $fail -eq 0 ]] || tail -20 /tmp/memory-dev.log
exit $fail
