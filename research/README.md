# Research: a small harness for weak open models

This is the project this repository started as, kept here as research. It asked: *can a small open model solve more
Python bug-fix tasks if it is wrapped in a harness that retries against real tests, writes lessons from its own mistakes,
and sees only the relevant code?* It is **not** the product pitch any more (see the [main README](../README.md)), but
its code is still used by the product (mistake memory, the code verifier, the context graph, the model adapter) and its
measurements are the only benchmark evidence in the repository, so they stay, unchanged and honest.

**Honest summary.** Retrying against tests repaired 2 of 21 held-out tasks on one model (a real but small effect). Memory
and the context graph showed no measurable effect because the models already pass almost everything. No Meta model was
measured. The claim that a weak model gains from the harness is only partly supported.

> Paths in this page (`benchmark/`, `results/`, `RESULTS.md`, `SPEC.md`) are where the files are today; they are being moved
> under `research/` once the last scheduled experiments finish.

## How it works

Three modules, one loop:

```mermaid
flowchart LR
    T[Task: buggy code + tests + description] --> G[Context graph<br/>ast + PageRank picks relevant files]
    M[(Mistake memory<br/>lessons.json)] -->|top 3 relevant lessons| P[Prompt]
    G --> P
    P --> L[Model: any OpenAI-compatible endpoint]
    L -->|full fixed files| V[Verifier<br/>unittest in a subprocess, timeout]
    V -->|pass| D[Done]
    V -->|fail: trimmed traceback| R[Reflect: write a general lesson]
    R --> M
    R -->|error + lesson, up to 3 retries| L
    D -->|lessons that helped are promoted,<br/>useless ones pruned| M
```

1. **Loop: attempt, check, retry** (`src/kintsugi/loop.py`, `verifier.py`).
   The model returns whole files in fenced code blocks (an unfenced `# file:` reply is accepted too). The verifier copies the task to a temp directory, writes the files there and runs `python -m unittest` in a **separate process with a timeout**. Model output is never imported into the harness, and API keys are stripped from the child environment. On failure the trimmed traceback goes back to the model. Each retry sends only the task, the latest attempt and its error, plus one line per earlier failure, so long chains never outgrow a small context window. A reply identical to an earlier attempt (or to the original code) is called out explicitly. Retries are capped (default 3). The model may not edit tests.

2. **Mistake memory** (`src/kintsugi/memory.py`).
   After a failed attempt the model writes one short, *general* lesson ("When ... do ..."); lessons that name the task's own functions are dropped. The lesson is shown on the very next retry and stored in a JSON file with its evidence trail. Near-duplicates are merged (token Jaccard >= 0.6). On later tasks the top 3 lessons by keyword overlap and track record are added to the prompt. A lesson starts as a *candidate*, is *promoted* only after a task that used it passed, and is *pruned* after 3 uses with no win. A task is never shown a lesson that only it produced. If the API itself fails (rate limit, timeout), nothing is learned or punished.

3. **Context graph** (`src/kintsugi/graph.py`).
   Every source file is parsed with `ast` into definitions (functions, classes, methods, constants, modules) and edges (calls, name references, imports). The names used by the tests (and named in the description) seed a **personalized PageRank**. The model then sees the full text of the top-ranked files (the only files it may edit), read-only snippets of connected definitions elsewhere, and a signature-only map of the rest.

Try the graph on a benchmark task:

```
$ kintsugi graph benchmark/tasks/m08_scheduler
22 definitions, 13 edges
  jobs.<module> --imports--> schedule_config.INTERVALS
  jobs.interval_for --references--> schedule_config.INTERVALS
  jobs.next_run --calls--> jobs.interval_for
  ...
Files shown in full for this task: jobs.py, schedule_config.py
```

## Quick start

```bash
git clone https://github.com/niranjanpatil0808-max/KINTSUGI.git && cd KINTSUGI   # then follow the steps below from the repository root
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Offline: the harness's own tests, the benchmark check, and the pipeline on the mock model
python -m unittest discover -s tests
python benchmark/check_tasks.py              # every bug fails, every reference fix passes
python benchmark/run_benchmark.py --model mock

# Real model: any OpenAI-compatible endpoint (defaults to Groq)
export GROQ_API_KEY=...                      # free key from console.groq.com
kintsugi models                              # which model names does my key allow?
export KINTSUGI_MODEL=qwen/qwen3.8-27b       # pick one from that list
kintsugi fix benchmark/tasks/s03_binary_search -v
python benchmark/run_benchmark.py --model openai
```

Other endpoints (Meta Llama API, Together, Fireworks, a local Ollama server):

```bash
export KINTSUGI_BASE_URL=http://localhost:11434/v1   # e.g. Ollama
export KINTSUGI_MODEL=llama3.1:8b
export KINTSUGI_API_KEY=anything
export KINTSUGI_MAX_TOKENS=4096                      # keep prompt + max_tokens under your per-minute limit
```

**Running the benchmark without a computer.** `.github/workflows/benchmark.yml` runs it on GitHub's servers. Add your key as the repository secret `KINTSUGI_API_KEY`, edit `benchmark/run.config` (base URL, then one `model|max_tokens|repeats|modes` entry per model) and push: the run starts and commits its results to `results/`. Rebuild the all-runs page with `python benchmark/build_results_md.py`.

## Benchmark

32 hand-written bug-fix tasks in `benchmark/tasks/`, each with a description, buggy code and a `unittest` suite. Reference fixes live in `benchmark/solutions/` and are never shown to the model. `benchmark/check_tasks.py` verifies that every buggy version fails and every reference fix passes.

- **16 single-function bugs**, easy and medium (off-by-one, wrong operator, missing sort, wrong wrap-around, tie ordering, ...).
- **8 multi-file mini-projects** where the fix depends on another file (a helper, a constant, an error class, a units comment) and two unrelated "distractor" files add noise.
- **8 hard tasks** with long, rule-heavy specifications (semantic-version precedence, word wrapping, a TTL cache, CSV quoting, topological sort, largest-remainder money splitting, business days, nested run-length decoding).
  **These were added after the first real runs**, because the original 24 tasks were passed 100% in every mode by both capable models and so could not separate the modes. I wrote all 8 before running any model on them and kept all of them whatever the results were.
- **Split** (`benchmark/split.json`): 11 warmup tasks and 21 held-out tasks (5 of them hard). Memory modes learn on warmup first; **pass rates are reported on the held-out tasks only**. Memory keeps learning while it goes through the held-out tasks one after another, but no task ever sees its own lesson.

| Mode | Retries | Memory | Context |
|---|---|---|---|
| `baseline` | 0 | no | all files |
| `loop` | 3 | no | all files |
| `loop+memory` | 3 | yes | all files |
| `full` | 3 | yes | context graph |

## Results

**Which models.** The free Groq account used here offers no Llama chat model (Groq's list for this key: `allam-2-7b`, `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, plus speech and safety models). **None of the models measured is from Meta.** The harness is model-agnostic and the hackathon target is Llama-class models, so running the same workflow on a Llama endpoint is the first thing to do with a key for one.

**What the data shows so far** (details and every run: [RESULTS.md](../RESULTS.md)):

1. **Retrying against the tests works.** On `qwen/qwen3.8-27b` the baseline fails 2 of 21 held-out tasks (`s14_fibonacci` and `h08_nested_decode`). In `loop` mode both are repaired after the model sees the test error, in both complete runs on the 32-task set. The first attempt of `loop` is the same request as the baseline's, so the retry is what changed the outcome. That is 2 tasks out of 21 in one model: a real but small effect.
2. **Memory and the context graph show no measurable effect yet.** The models already pass almost everything, so there is nothing for them to improve. The memory module does what it should (the model wrote general lessons such as *"When implementing parsers or decoders, ensure that validation for structural integrity, such as balanced delimiters, is performed after processing the entire input"*; the lessons were shown to later tasks and promoted after those tasks passed), but I cannot claim it improved a pass rate.
3. **The weak model is only partly measured.** `allam-2-7b` (7B) is the only model here with real headroom (2/16 baseline on the original set; 3/21 in loop mode on the 32-task set in batch 1). Its memory and full-mode runs still stopped at Groq's daily token limit (see batch 1 below), so memory and the graph have still not been compared on it.
4. **`gpt-oss-20b`:** baseline 20/21 on the 32-task set; its retry modes did not finish because of the 200,000 tokens-per-day limit.

**Batch 1 (2026-10-22): more headroom, large projects, the weak model.** Same harness, run on GitHub Actions with a Groq key; every table is in [RESULTS.md](../RESULTS.md) (copied unchanged there) and the raw data is in `results/20261022-*`. In short:

- **Retries again repaired every first-attempt failure, now on a deliberately weakened model.** `gpt-oss-20b` with `reasoning_effort=low` (a weakened setting I chose to create headroom; not the model's normal behaviour), 3 repeats at temperature 0.6, loop mode: 63 task runs, 6 failed the first attempt, and all 6 were repaired by the retries (first attempt 90%, after retries 100%, +9.5 pp, 95% interval +0.0 to +22.2 pp over tasks). Together with the earlier `qwen3.8-27b` result (2 of 2 repaired) that is 8 of 8 repaired first-attempt failures on two models. Plainly: this supports "a retry that shows the test error fixes most failures a model makes on these tasks". It does not support a claim about how large the effect is on other tasks or models: there were only 6 failures to repair, the interval's lower end touches zero, and this run had no separate baseline mode (the first attempt of `loop` is the same request).
- **The context graph cut tokens by about 45% on the large multi-file tasks with no loss in the pass rate, but accuracy could not be compared.** On the 7 held-out large-project tasks both `gpt-oss-20b` (low effort) and `qwen3.8-27b` passed 7 of 7 in every mode (baseline, loop and loop+graph). Tokens per task fell from about 3,700 to about 2,040 (`gpt-oss-20b`) and from about 3,850 to about 2,090 (`qwen3.8-27b`). One run each. Because every mode scores 100%, this says the graph made the prompts smaller without hurting these tasks; it does not show the graph makes a model solve more. The graph rules were tuned by me on these multi-file tasks (disclosed under Limitations), so the size of the saving may not carry over to other projects.
- **`allam-2-7b` (7B) on the large tasks: not a valid pass rate.** The API rejected the full-context prompts (baseline and loop) for all 7 tasks as too long. With the graph, 4 of 7 prompts fit and the model failed all 4; the other 3 were still rejected. So the graph can make a project fit a small model's context, but that did not make the model solve these tasks.
- **`allam-2-7b` on the main set: weak, and the memory test did not finish.** Loop mode passed 3 of 21 held-out tasks (first attempt 10%, retries repaired 1 of 19 failures, 0 of 5 hard tasks). `loop+memory` stopped at Groq's 500,000 tokens-per-day limit after 14 of 21 tasks and `full` did not start. So the memory comparison on the one model with headroom is still missing.
- **Nothing was rejected by the extra `reasoning_effort` request field**: the `gpt-oss-20b` runs completed with no API errors.

What batch 1 does *not* tell us: whether memory or the graph improve accuracy (the capable models pass everything and the weak model's memory run did not finish), anything about a Meta/Llama model, or anything about real-world bugs (the tasks are small and written by me).

**Main table** (`qwen/qwen3.8-27b`, 32-task set, 21 held-out tasks, one run, first version of the retry loop; copied unchanged from `results/20261021-163652-openai.md`):

Model: `qwen/qwen3.8-27b` · held-out tasks: 21 (5 hard) · repeats: 1 · max retries: 3 · temperature: 0.0

| Mode | Pass rate (held-out) | Hard tasks only | Avg attempts | Model calls (scored tasks) | Tokens (scored tasks) |
|---|---|---|---|---|---|
| baseline | 90% (19/21) | 80% (4/5) | 1.00 | 21 | 15,219 |
| loop | 100% (21/21) | 100% (5/5) | 1.10 | 23 | 19,127 |
| loop+memory | 100% (21/21) | 100% (5/5) | 1.05 | 23 | 17,218 |
| full | 100% (21/21) | 100% (5/5) | 1.05 | 23 | 15,250 |

A later run with the bounded-context loop gave the same baseline, loop and loop+memory results (`full` was stopped by the daily quota); see [RESULTS.md](../RESULTS.md).

**Invalid and incomplete runs are kept, not hidden.** One `gpt-oss-20b` run was invalid (my token setting made Groq reject many requests; the code of that day scored them as failures); several runs stopped at the daily token limit; one `allam-2-7b` run was dominated by a parser bug. [RESULTS.md](../RESULTS.md) lists all of them with the reason.

## Limitations of this research

- **No Meta model was measured** (see Results). The claim in the project brief, that a small open model gains from the harness, is only partly tested.
- **Small effect, small sample.** The one clear gain is 2 repaired tasks out of 21, on one model, in single runs. One task is about 5 percentage points. Temperature 0 is not fully deterministic on the hosted models (the same prompts occasionally gave different results between runs).
- **Ceiling effects.** Capable models pass almost everything, which leaves no room to measure memory or the graph. Only 5 held-out tasks are hard.
- **The hard tier was added after seeing the first results** (disclosed above). All 8 were kept whatever the outcome.
- **Free-tier limits shaped the experiment.** Groq's free tier caps tokens per minute and per day (200,000 per day for `gpt-oss-20b` and `qwen3.8-27b`), so complete multi-repeat runs are not possible in one day.
- **Tasks are written by the same person who wrote the harness.** I tried to keep the bugs realistic and the descriptions neutral, but this is not an independent benchmark.
- **Graph rules were tuned on the 8 multi-file tasks.** I inspected which files it picked and fixed two rules (ignore `__dunder__` links; plain description words do not seed methods) before any model results existed. It still favours the graph on this benchmark.
- **Name-based resolution.** The graph links calls by name, not by type, so two unrelated functions with the same name can be linked.
- **Memory retrieval is keyword overlap**, not embeddings.
- **The model sees the tests.** That measures "fix to pass given tests", not "find an unknown bug".

## What's next

- Run the full ablation on a Llama model, and on `allam-2-7b`, where there is headroom to measure memory and the graph.
- More and harder tasks, including real open-source bug histories, and several temperature-above-0 repeats per mode so that noise can be measured.
- Embedding-based lesson retrieval compared against keyword retrieval; lessons written only from mistakes the model actually corrected.

