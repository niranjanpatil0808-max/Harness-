#!/usr/bin/env bash
# Runs every browser test, each against a fresh scripted workspace. Needs node + playwright (see README.md here).
set -u
cd "$(dirname "$0")/../.."
status=0
for t in flow ease models internet plugins safety improve pwa voice settings automations unread push; do
  rm -rf /tmp/kt-ui && (KINTSUGI_TOKEN=tok123 python tests/ui/serve_mock.py /tmp/kt-ui 8804 >/tmp/kt-ui.log 2>&1 & echo $! >/tmp/kt-ui.pid)
  sleep 2
  echo "== $t"; timeout 180 node "tests/ui/$t.js" 2>&1 | grep -v agent-proxy || status=1
  kill "$(cat /tmp/kt-ui.pid)" 2>/dev/null; sleep 1
done
exit $status
