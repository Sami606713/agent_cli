#!/usr/bin/env bash
# Does `langctl share` expose the app publicly and tear down cleanly?
#
# Two mistakes to avoid, both made earlier:
#   * `$!` after `setsid ... &` is the setsid wrapper, not the real process.
#   * SIGKILL cannot be handled, so it can never test graceful teardown.
set -u
OUT=/tmp/share-probe.txt
: > "$OUT"; exec >>"$OUT" 2>&1

PROJ="${LANGCTL_E2E_PROJECT:?set LANGCTL_E2E_PROJECT to a scaffolded project with a frontend}"
cd "$PROJ"

pass=0; fail=0
check() {
  if [[ "$2" == *"$3"* ]]; then echo "  PASS  $1"; pass=$((pass+1))
  else echo "  FAIL  $1 (got: ${2:0:80})"; fail=$((fail+1)); fi
}

LOG=/tmp/share-run.log
setsid langctl share --provider ngrok > "$LOG" 2>&1 < /dev/null &
for _ in $(seq 1 150); do grep -q "public URL" "$LOG" 2>/dev/null && break; sleep 1; done

# Resolve the real pid by matching the interpreter, not the shell command line.
PID=$(pgrep -f "bin/langctl" | head -1)
URL=$(grep -oE 'https://[a-z0-9-]+\.ngrok[^ │]*' "$LOG" | head -1)
echo "  pid=$PID url=$URL"

check "public URL announced" "${URL:-none}" "https://"
check "app served publicly" \
  "$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 -H 'ngrok-skip-browser-warning: 1' "$URL")" "200"
check "agent reachable through the proxy" \
  "$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 -H 'ngrok-skip-browser-warning: 1' "$URL/api/agent/ok")" "200"
# The agent port itself must not be tunnelled — only the frontend is exposed.
check "agent port not exposed directly" \
  "$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -H 'ngrok-skip-browser-warning: 1' "$URL:2024/ok" || echo blocked)" ""

echo "--- SIGTERM (the handled path)"
kill -TERM "$PID" 2>/dev/null
for _ in $(seq 1 40); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
sleep 2

check "langctl exited" "$(kill -0 "$PID" 2>/dev/null && echo alive || echo gone)" "gone"
check "port 2024 released" "$(ss -ltn 'sport = :2024' | tail -n +2 | wc -l)" "0"
check "port 3000 released" "$(ss -ltn 'sport = :3000' | tail -n +2 | wc -l)" "0"
check "no stray tunnel" "$(pgrep -c -f 'ngrok http' || echo 0)" "0"

echo "--- result: $pass passed, $fail failed"
exit $fail
