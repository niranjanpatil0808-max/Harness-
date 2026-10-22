# Browser tests for the web interface

They drive the real page in headless Chromium against a workspace with a scripted model (no API key needed).
They are not part of `python -m unittest` because they need Node and Playwright.

```bash
npm install playwright            # or use any Playwright install; set PLAYWRIGHT_MODULE / CHROMIUM if needed
rm -rf /tmp/ws && KINTSUGI_TOKEN=tok123 python tests/ui/serve_mock.py /tmp/ws 8804 &
node tests/ui/flow.js             # chat, markdown + XSS sanitising, approval card, lessons, drawer tabs, new agent, phone width
rm -rf /tmp/ws && KINTSUGI_TOKEN=tok123 python tests/ui/serve_mock.py /tmp/ws 8804 &   # fresh server for the next one
node tests/ui/safety.js           # secrets never shown or exported, Safety tab, export, delete an agent, isolation wording
```

`pwa.js` checks the service worker, that `/api` is never cached, the manifest, thumb-sized touch targets and the offline shell on a phone-sized screen; `voice.js` fakes the browser's speech engines to check speech-to-text, read-aloud (backlog never spoken), the hands-free loop, a blocked microphone and an unsupported browser. `improve.js` covers self-improvement.

To run them all: `tests/ui/run_all.sh` (set `CHROMIUM` and `PLAYWRIGHT_MODULE` if needed). Each prints `no errors` on success. Screenshots go to `$SHOTS` (default `/tmp`).
