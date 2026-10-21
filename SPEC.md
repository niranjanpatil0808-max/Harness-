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
| Model | `llama-3.1-8b-instant` on Groq | Free tier, OpenAI-compatible, weak enough to leave room for gains |
| Adapter | stdlib `urllib`, OpenAI chat format | No dependencies; works with Groq, Together, Fireworks, Meta Llama API, Ollama |
| Env vars | `KINTSUGI_BASE_URL`, `KINTSUGI_MODEL`, `KINTSUGI_API_KEY` (falls back to `GROQ_API_KEY`) | Keys never in code |
| Temperature | 0 | Least noise per call on a small budget |
| Retries | 3 (4 attempts total) | Brief default |
| Fix format | Whole files in fenced blocks tagged `# file: path` | Most reliable for an 8B model; files are small |
| Test runner | `python -m unittest` in a subprocess, 10 s timeout, temp copy, API keys stripped from env | Safe and dependency-free |
| Error fed back | Last 2000 characters of the test output | The traceback tail carries the signal |
| Lessons | ≤ 2 sentences, ≤ 300 chars, start with "When" | Short and general |
| Dedup | Token Jaccard ≥ 0.6 → merge | Cheap and explainable |
| Retrieval | Top 3 by keyword overlap / √(keywords) × (0.5 + smoothed win rate), +0.25 if promoted | Relevance first, track record second |
| Promote / prune | Promote after first win; prune after 3 uses with 0 wins | Keep what works (Harness² idea) |
| Self-leak guard | A lesson whose only evidence is task X is never shown to task X | Honest scoring |
| Graph | `ast` nodes (module, function, class, method, constant); edges calls / references / imports | Simple and standard library only |
| Ranking | Personalized PageRank, damping 0.85, reverse-edge weight 0.3, seeds from test imports/calls and description names (top-level only) | Aider repo-map idea |
| Context | Files ≥ 30% of top file's score in full (8000-char budget), up to 4 read-only snippets ≥ 5% of top node, signature map for the rest | Small prompt, still navigable |
| Editing in graph mode | Only files shown in full may be edited | Prevents overwriting a file the model never saw |
| Benchmark | 24 tasks: 16 single-function, 8 multi-file with 2 distractor files each | Measurable for all three modules |
| Split | 8 warmup / 16 held-out, fixed in `benchmark/split.json` | No scoring on tasks the memory trained on |
| Modes | baseline, loop, loop+memory, full | Ablation shows which module helps |

## Safety
Model output is only ever executed by the verifier's child process, in a temp directory, with a
timeout. Writes outside the task folder are refused. This is not a full sandbox: the child process
runs with the user's permissions. Do not point the harness at code or models you don't trust.
