#!/usr/bin/env bash
# Does SSE stream *incrementally* through the Next.js proxy route?
#
# A buffering proxy passes every status-code assertion and still ruins the
# product: the user waits, sees nothing, then the whole answer appears at once.
# So this measures arrival *times*, not just the final body.
set -u
OUT=/tmp/sse-probe.txt
: > "$OUT"; exec >>"$OUT" 2>&1


STUB_PORT=18777
WEB_PORT=3111

# Upstream stub: 5 SSE events, 400ms apart.
cat > /tmp/sse_stub.py <<'PY'
import http.server, socketserver, time, sys
PORT = int(sys.argv[1])
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_GET(self):
        if self.path == "/ok":
            self.send_response(200); self.send_header("content-length","2")
            self.end_headers(); self.wfile.write(b"ok"); return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        for i in range(5):
            payload = f"data: chunk{i}\n\n".encode()
            self.wfile.write(b"%x\r\n" % len(payload) + payload + b"\r\n")
            self.wfile.flush()
            time.sleep(0.4)
        self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()
    def log_message(self, *a): pass
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", PORT), H) as s:
    s.serve_forever()
PY

python3 /tmp/sse_stub.py "$STUB_PORT" &
STUB=$!
sleep 1

cd "${AGENTCTL_E2E_PROJECT:?set AGENTCTL_E2E_PROJECT}/web"
AGENT_PROXY_TARGET="http://127.0.0.1:$STUB_PORT" npx next dev --port "$WEB_PORT" > /tmp/sse-next.log 2>&1 &
WEB=$!
for i in $(seq 1 120); do curl -sf -o /dev/null "http://127.0.0.1:$WEB_PORT/" && break; sleep 1; done

echo "== direct from stub (baseline)"
curl -sN "http://127.0.0.1:$STUB_PORT/stream" | while IFS= read -r line; do
  [ -n "$line" ] && echo "  $(date +%s.%N) $line"
done

echo "== through the Next.js proxy"
curl -sN -D /tmp/sse-headers.txt "http://127.0.0.1:$WEB_PORT/api/agent/stream" \
  | while IFS= read -r line; do
      [ -n "$line" ] && echo "  $(date +%s.%N) $line"
    done

echo "== response headers from the proxy"
grep -iE "content-type|cache-control|x-accel-buffering|content-encoding" /tmp/sse-headers.txt

kill "$WEB" "$STUB" 2>/dev/null
pkill -f "nex[t]-server" 2>/dev/null
echo done
