# Kintsugi design spec

## Claim
A small open model fixes more buggy Python code with the harness than without it, because the
harness feeds back test errors, keeps short lessons from earlier mistakes, and shows the model
only the connected code it needs. Every reported number comes from a results file.

## Scope
Exactly three modules: loop, mistake memory, context graph. No extra features until all three
work and are measured.

## Defaults chosen (and why)
| Decision | Default | Reason |
|---|---|---|
| Model | Any OpenAI-compatible endpoint; `kintsugi models` lists what a key can use | The planned `llama-3.1-8b-instant` is not on the account used here, so the runs use what Groq lists (`allam-2-7b`, `gpt-oss-20b`, `qwen3.8-27b`) |
| Adapter | stdlib `urllib`, OpenAI chat format | No dependencies; works with Groq, Together, Fireworks, Meta Llama API, Ollama |
| Env vars | `KINTSUGI_BASE_URL`, `KINTSUGI_MODEL`, `KINTSUGI_API_KEY` (falls back to `GROQ_API_KEY`) | Keys never in code |
| Temperature | 0 | Least noise per call on a small budget (still not fully deterministic on hosted models) |
| Retries | 3 (4 attempts total) | Brief default |
| Fix format | Whole files in fenced blocks tagged `# file: path`; unfenced `# file:` sections are accepted when a reply has no fenced block | Most reliable for small models; one model omitted the opening fence |
| Test runner | `python -m unittest` in a subprocess, 10 s timeout, temp copy, API keys stripped from env | Safe and dependency-free |
| Error fed back | Last 2000 characters of the test output | The traceback tail carries the signal |
| Retry context | Task + latest attempt + its error + one summary line per earlier failure; repeats (or unchanged original code) are called out | Bounded tokens, fits small context windows, stops the model resubmitting the same code |
| API errors | 400/422 (and 413 not about the per-minute limit) = rejected request, scored as a failed task; 413 over the per-minute limit, 429, 5xx, timeouts = `ApiError`: retried after a pause, never scored, never teaches memory, a mode with unanswered tasks is `INCOMPLETE`; a daily quota stops the run | An outage must not look like a model failure |
| Lessons | ≤ 2 sentences, ≤ 300 chars, start with "When"; dropped if they name the task's own functions, classes or constants | Short and general |
| Dedup | Token Jaccard ≥ 0.6 → merge | Cheap and explainable |
| Retrieval | Top 3 by keyword overlap / √(keywords) × (0.5 + smoothed win rate), +0.25 if promoted | Relevance first, track record second |
| Promote / prune | Promote after first win; prune after 3 uses with 0 wins | Keep what works (Harness² idea) |
| Self-leak guard | A lesson whose only evidence is task X is never shown to task X | Honest scoring |
| Graph | `ast` nodes (module, function, class, method, constant); edges calls / references / imports | Simple and standard library only |
| Ranking | Personalized PageRank, damping 0.85, reverse-edge weight 0.3, seeds from test imports/calls and description names (top-level only) | Aider repo-map idea |
| Context | Files ≥ 30% of top file's score in full (8000-char budget), up to 4 read-only snippets ≥ 5% of top node, signature map for the rest | Small prompt, still navigable |
| Editing in graph mode | Only files shown in full may be edited | Prevents overwriting a file the model never saw |
| Benchmark | 32 tasks: 16 single-function, 8 multi-file with 2 distractor files each, 8 hard (added after the first results showed the other 24 were saturated) | Measurable for all three modules |
| Split | 11 warmup / 21 held-out (5 hard), fixed in `benchmark/split.json` | No scoring on tasks the memory trained on |
| Reporting | Pass rate over held-out tasks only; calls and tokens counted for scored tasks only; incomplete modes get no number | Modes must be comparable and no number may be invented |
| Modes | baseline, loop, loop+memory, full | Ablation shows which module helps |

## Safety
Model output is only ever executed by the verifier's child process, in a temp directory, with a
timeout. Writes outside the task folder are refused. This is not a full sandbox: the child process
runs with the user's permissions. Do not point the harness at code or models you don't trust.
