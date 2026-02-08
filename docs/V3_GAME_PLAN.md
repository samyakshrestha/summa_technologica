# V3 Game Plan (Decision-Theoretic)

## Executive Decision
Yes, moving to V3 is the correct direction.
V2 is now a stable baseline, and the highest expected-value work is to improve scientific usefulness (novelty + testability + grounding) without increasing fragility.

## North Star
V3 should make the system better at producing hypotheses that are:
- more original,
- more testable,
- better grounded in real literature,
- equally or more reliable than V2,
- still simple to operate and maintain.

## Decision Principle
For each proposed V3 feature, use:

**Expected Utility = (Impact on research quality × Probability of success) − (Engineering cost + reliability risk + complexity tax).**

Only ship features that are positive on expected utility and do not degrade reliability.

## Current Baseline (What V2 Already Gives Us)
- Structured, schema-validated outputs.
- Grounded-citation retrieval path with fallbacks.
- Ranking and Summa rendering fallback.
- Failure-contract handling instead of silent crashes.

This means V3 should target quality and calibration, not more scaffolding.

## V3 Priorities (Ranked by Expected Value)

## 1) Evidence Quality Upgrade (Highest EV)
Goal: improve retrieval precision and citation usefulness before generation.

Why first:
- Better evidence improves every downstream stage.
- Low implementation risk relative to novelty-focused model changes.

Candidate work:
- Query expansion from problem memo + domain aliases.
- Relevance reranking and lightweight deduping by semantic similarity.
- Prefer papers with abstracts and enforce minimal evidence quality filters.

Exit criteria:
- Higher grounded citation quality on manual spot checks.
- No increase in pipeline error rate.

## 2) Hypothesis Novelty Engine
Goal: reduce “obvious rephrasings” and produce mechanism-level diversity.

Why second:
- Biggest value for brainstorming originality.
- Moderate implementation risk; benefits from better retrieval in Priority 1.

Candidate work:
- Explicit mechanism slots (cause, substrate, intervention, measurable signal).
- Diversity constraints that force non-overlapping mechanisms.
- Anti-template checks to reject paraphrase-only variants.

Exit criteria:
- Manual novelty rubric improves on a fixed prompt panel.
- Distinctness matrix quality improves without harming plausibility.

## 3) Falsification Strength and Experiment Design
Goal: make predictions sharper and easier to test.

Why third:
- Directly supports scientific utility.
- Medium effort, high practical value.

Candidate work:
- Require quantitative/conditional predictions where possible.
- Add “minimum discriminative experiment” field quality checks.
- Add contradiction-sensitive tests (what would disprove each hypothesis).

Exit criteria:
- Increased falsifiability scores on manual rubric.
- Fewer vague predictions in sampled outputs.

## 4) Ranking Calibration
Goal: make ranking less style-sensitive and more criterion-faithful.

Why fourth:
- Improves trust in top hypothesis selection.
- Depends on better upstream hypothesis quality.

Candidate work:
- Calibrated scoring prompts with clear tie policy.
- Stability checks (same prompt, small prompt perturbations, same winner distribution).

Exit criteria:
- Ranking stability improves on repeated runs.
- Better agreement with human judges on top-1 choice.

## 5) Observability and Reproducibility
Goal: make debugging and research iteration easier.

Why fifth:
- Good ROI for long-term development speed.
- Should be lightweight and optional.

Candidate work:
- Optional run manifests for V2/V3 single runs.
- Per-stage latency and failure tags.
- Version stamps for prompt/schema/config.

Exit criteria:
- Faster root-cause analysis during failures.
- Minimal runtime overhead.

## What Not to Do (For Now)
- Do not add many new agents just to add agents.
- Do not optimize for cosmetic output improvements over scientific utility.
- Do not widen scope (memory, multi-session orchestration, UI) until core hypothesis quality is stronger.

## Agent Count Policy for V3
Keep agent count minimal unless a split gives measurable gains.
Default recommendation: keep the current conceptual stages, improve prompts/contracts/tools first.

Rationale:
- More agents increase orchestration complexity and failure surface.
- Most gains likely come from better retrieval, constraints, and validation, not role proliferation.

## Implementation Plan

## Phase A: Stabilize Baseline for V3 Work
- Freeze current V2 contract and schema.
- Add a small fixed evaluation subset for fast iteration.

Deliverable:
- `docs/V3_BASELINE.md` with frozen assumptions and known limits.

## Phase B: Evidence + Novelty Core
- Implement Priority 1 and Priority 2.
- Run fast eval subset per change.

Deliverable:
- First V3 alpha branch with measurable novelty/grounding improvement.

## Phase C: Falsification + Ranking Calibration
- Implement Priority 3 and Priority 4.
- Validate with focused rubric checks.

Deliverable:
- V3 beta with stronger testability and ranking trust.

## Phase D: Observability and Hardening
- Implement Priority 5.
- Final reliability sweep.

Deliverable:
- V3 release candidate with docs and migration notes.

## Stop Conditions (Where We Stop)
Stop iterating V3 when all are true:
- Reliability is at least V2-level.
- Manual novelty/testability rubric gains are consistently positive.
- Runtime/cost does not exceed acceptable budget envelope.
- Additional feature ideas have lower expected utility than maintenance.

At that point, freeze V3 and switch to either:
- targeted domain packs (physics, math), or
- controlled research experiments (human-in-the-loop hypothesis vetting).

## Immediate Next Step
Start with **Priority 1 (Evidence Quality Upgrade)** in a small scoped implementation.
It has the best expected utility and improves every downstream stage while keeping risk low.

---

## Architect Review Comments (for Codex)

The plan above is directionally correct. Below are concrete implementation notes,
missing priorities, and file-level guidance so that each work package can be
implemented cleanly without guesswork.

### MISSING PRIORITY 0: Model Routing (insert BEFORE Priority 1)

The single biggest quality bottleneck in V2 is that gpt-4o-mini handles every
stage. This small model produces generic hypotheses and sometimes ignores prompt
constraints. Model routing — assigning a stronger model to creative stages and
keeping the cheap model for structural stages — has the highest expected value of
any change because it improves output quality with zero prompt/code refactoring.

Implementation:
- In `summa_technologica/config.py` (`Settings`), add a field `creative_model: str`
  defaulting to the same value as `model` (so existing behavior is unchanged).
  Read it from env var `CREATIVE_MODEL`.
- In `summa_technologica/crew_v2_stages.py` → `_run_agent_task()`, the Agent is
  currently created with `llm=settings.model`. Change this so that the caller can
  pass an optional `model_override: str | None`. When set, use that instead of
  `settings.model`.
- In `summa_technologica/crew_v2.py` → `run_summa_v2()`, pass
  `model_override=settings.creative_model` for these stages:
  - hypothesis_generator
  - critic
  - summa_composer
  Leave problem_framer, literature_scout, and ranker on `settings.model` (cheap).
- This requires NO prompt changes, NO schema changes, and NO new agents.
- Test: run benchmarks with `CREATIVE_MODEL=gpt-4o` and `MODEL=gpt-4o-mini`.
  Expect measurable improvement in novelty and summa completeness.

Exit criteria:
- Benchmark still passes GO.
- Hypothesis novelty improves on manual inspection of 3-5 samples.
- Cost per run stays under $0.50 (currently ~$0.02 with gpt-4o-mini everywhere).

### Priority 1: Evidence Quality Upgrade — File-Level Guide

The current retrieval path lives in `summa_technologica/semantic_scholar.py`.
Key function: `retrieve_grounded_papers()` which calls `build_dual_queries()`
to produce at most 2 queries (the raw question + refined_query from problem_framer).

Specific changes:
1. **Query expansion** — modify `build_dual_queries()` (or add a new function
   `build_expanded_queries()`) to accept the full problem_memo dict. Extract
   `thesis_directions` (list of 2 strings) and `assumptions` (list of 3-7 strings)
   to generate additional query variants. Cap total queries at 4-5 to avoid
   rate-limiting. File: `summa_technologica/semantic_scholar.py`.

2. **Abstract filter** — in `_parse_paper()`, currently papers with empty abstracts
   are accepted (abstract defaults to ""). Add a quality filter: skip papers
   where `abstract` is empty or shorter than 50 characters. This is a one-line
   change in `_parse_paper()`. File: `summa_technologica/semantic_scholar.py`.

3. **Citation-count reranking** — after merging papers in `retrieve_grounded_papers()`,
   sort by citation_count descending before returning. This costs zero API calls
   and pushes higher-signal papers to the top of the list that the LLM sees.
   File: `summa_technologica/semantic_scholar.py`.

4. **Update the caller** — in `summa_technologica/crew_v2.py`, pass
   `problem_memo` to the retrieval function so it can use expanded queries.

Tests to add in `tests/test_semantic_scholar.py`:
- Test that `build_expanded_queries()` with a full problem_memo produces 3-5 queries.
- Test that papers with empty abstracts are filtered out.
- Test that returned papers are sorted by citation_count descending.

### Priority 2: Hypothesis Novelty Engine — File-Level Guide

This is primarily a prompt change plus a post-processing validator.

1. **Mechanism slots** — modify `hypothesis_generator_task` in
   `summa_technologica/config/tasks_v2.yaml`. Add required fields to each
   hypothesis object:
   - `mechanism_cause`: string (the proposed causal factor)
   - `mechanism_substrate`: string (the system or entity it acts on)
   - `mechanism_intervention`: string (how to manipulate it experimentally)
   - `mechanism_signal`: string (what measurable change to expect)
   These force the LLM to think mechanistically rather than paraphrase.

2. **Anti-template validation** — add a function `_check_novelty_diversity()` in
   `summa_technologica/crew_v2_postprocess.py`. After normalizing hypotheses,
   check that no two hypotheses share the same `mechanism_cause`. If duplicates
   exist, flag them in the distinctness_matrix or trigger a regeneration.

3. **Schema update** — add the 4 mechanism fields to
   `schemas/hypothesis_schema.json` as optional (not required), so existing V2
   outputs remain valid. Make them required only after the prompt reliably
   produces them.

4. **Normalization** — in `_normalize_generated_hypotheses()` in
   `crew_v2_postprocess.py`, extract the mechanism fields with fallbacks
   (same pattern as novelty_rationale).

### Priority 3: Falsification Strength — File-Level Guide

1. **Prompt change** — in `hypothesis_generator_task` in `tasks_v2.yaml`, add to
   the `falsifiable_predictions` field requirements:
   "Each prediction must be conditional ('If X, then Y within Z timeframe')
   or quantitative ('Metric M should change by at least N%'). Do NOT write
   vague predictions like 'performance will improve'."

2. **Post-processing check** — add `_validate_prediction_specificity()` in
   `crew_v2_postprocess.py`. Flag predictions that contain vague phrases like
   "will improve", "may show", "could lead to" without quantitative anchors.
   This is a warning/metric, not a hard rejection.

3. **Benchmark metric** — add a new metric `prediction_specificity_rate` to
   `summa_technologica/eval_compare.py` → `evaluate_v2_metrics()`. Count the
   fraction of predictions that pass the specificity check. Add a soft threshold
   (e.g., >= 0.5) as a non-blocking metric in the GO/NO_GO evaluation.

### Priority 4: Ranking Calibration — File-Level Guide

1. **Prompt refinement** — modify `ranker_task` in `tasks_v2.yaml`:
   - Add explicit tie policy: "Use 'tie' only when both hypotheses are
     genuinely indistinguishable on the axis. Default to picking a winner."
   - Add calibration anchor: "novelty = mechanism is not a restatement of
     existing work; plausibility = mechanism has empirical support;
     testability = a concrete experiment could falsify this within 1 year."

2. **Stability eval script** — create `eval/ranking_stability.py` that runs
   the same question 3 times and reports whether the top-1 winner is the same
   across runs. This is a new file, not a modification.

### Priority 5: Observability — File-Level Guide

1. **Run manifest** — at the end of `run_summa_v2()` in `crew_v2.py`, build a
   `_run_manifest` dict with: timestamp, model used, creative_model used,
   per-stage durations (use time.monotonic() before/after each stage), and
   config versions (hash of tasks_v2.yaml + agents_v2.yaml). Include in the
   final payload under a `_metadata` key (underscore-prefixed so schema
   validation ignores it, or add it as optional in the schema).

### Phase Restructuring (consolidated for Codex efficiency)

Consolidated into 2 WPs to minimize Codex context overhead. Each WP touches
clearly separated files with minimal overlap.

- **WP7: Infrastructure + Evidence** (Priority 0 + Priority 1)
  Model routing and retrieval improvements. These touch different files with
  zero overlap, so bundling is safe.

  Files to modify:
  - `summa_technologica/config.py` — add `creative_model` field to Settings
  - `summa_technologica/crew_v2_stages.py` — add `model_override` param to
    `_run_agent_task()` and `_run_json_stage()` and `_run_summa_composer_stage()`
  - `summa_technologica/crew_v2.py` — pass `model_override=settings.creative_model`
    for hypothesis_generator, critic, and summa_composer stages; pass
    `problem_memo` to retrieval call for expanded queries
  - `summa_technologica/semantic_scholar.py` — add `build_expanded_queries()`,
    add abstract quality filter in `_parse_paper()`, sort by citation_count in
    `retrieve_grounded_papers()`
  - `tests/test_semantic_scholar.py` — add tests for expanded queries, abstract
    filter, citation-count sort
  - `.env` — document new env var `CREATIVE_MODEL` (default: same as MODEL)

  Files NOT to modify: tasks_v2.yaml, agents_v2.yaml, crew_v2_postprocess.py,
  v2_contracts.py, schemas/, eval_compare.py.

  Verification: run `summa-run` on 1 physics question with
  `CREATIVE_MODEL=gpt-4o` and confirm output looks good. Run existing unit
  tests with `python -m pytest tests/`. Do NOT create new benchmark
  infrastructure or eval scripts.

- **WP8: Quality + Calibration** (Priority 2 + Priority 3 + Priority 4 + Priority 5)
  Prompt improvements, post-processing validators, ranking calibration, and
  basic observability. These all target the same files (tasks_v2.yaml,
  crew_v2_postprocess.py) so they belong together.

  Files to modify:
  - `summa_technologica/config/tasks_v2.yaml` — add mechanism slots to
    hypothesis_generator_task, add prediction specificity requirements to
    falsifiable_predictions, add tie policy and calibration anchors to
    ranker_task
  - `summa_technologica/crew_v2_postprocess.py` — add `_check_novelty_diversity()`
    for anti-template checks, add `_validate_prediction_specificity()` for
    vague-prediction detection, extract mechanism fields in
    `_normalize_generated_hypotheses()` with fallbacks
  - `summa_technologica/crew_v2.py` — add timing (time.monotonic) around each
    stage, build `_metadata` dict at end of run_summa_v2(), include in
    final payload
  - `schemas/hypothesis_schema.json` — add 4 mechanism fields as OPTIONAL
    (not required) so V2 outputs remain valid
  - `tests/test_crew_v2_helpers.py` — add tests for novelty diversity check
    and prediction specificity check

  Files NOT to modify: semantic_scholar.py, config.py, crew_v2_stages.py,
  v2_contracts.py, eval_compare.py.

  Verification: run `summa-run` on 1 physics question, confirm mechanism
  fields appear in output and predictions are more specific. Run existing
  unit tests with `python -m pytest tests/`. Do NOT create new benchmark
  scripts or eval infrastructure.

After both WPs are done, the user will run `summa-benchmark-compare` once
to confirm V3 is at least as reliable as V2.

### Important: What NOT to Do

- Do NOT create new eval scripts, benchmark runners, or comparison tools.
  The existing `summa-benchmark-compare` command is sufficient.
- Do NOT create new documentation files beyond updating this game plan.
- Do NOT add new agents or change the agent count.
- Do NOT modify eval_compare.py or create new files in eval/.
- Keep all changes minimal and surgical. If in doubt, do less.

### Code Style Guidelines (MUST follow for all V3 code)

The owner of this project prioritizes readability and simplicity above all
else. Every line of code should be understandable by someone who has never
seen the codebase. Follow these rules strictly:

**1. Docstrings must explain WHY, not restate the function name.**

Bad (V2 pattern — do NOT repeat this):
```python
def _accumulate_win(...):
    """Internal helper to accumulate win."""
```
Good:
```python
def _accumulate_win(...):
    """Add a win to the tally when one hypothesis beats another on a dimension."""
```
When writing new functions, write a one-line docstring that answers:
"If I had never seen this code, what would I need to know?"

**2. Add a pipeline overview comment at the top of crew_v2.py.**

The main orchestrator file should start with a plain-English summary of
the pipeline. Add this comment block at the top of `run_summa_v2()`:

```python
# Pipeline overview:
#   1. Problem Framer  — converts the question into a structured research memo
#   2. Paper Retrieval — searches Semantic Scholar for relevant papers
#   3. Literature Scout — summarizes retrieved papers into an evidence memo
#   4. Hypothesis Gen   — produces 3-5 distinct hypotheses grounded in evidence
#   5. Critic           — stress-tests hypotheses, adds objections and replies
#   6. Ranker           — compares hypotheses pairwise on novelty/plausibility/testability
#   7. Summa Composer   — renders the top hypothesis into Summa Theologica format
```

**3. Do NOT create tiny helper functions for trivial operations.**

If a helper is 1-3 lines and called once or twice, inline it. For example,
do NOT write:
```python
def _get_text_or_default(val, default):
    return val.strip() if isinstance(val, str) and val.strip() else default
```
Instead, just write the logic inline where it's used, or use a single
well-named utility if it's called 5+ times.

**4. Name functions for what they DO, not what they ARE.**

Bad: `_as_nonempty_text`, `_as_id`, `_as_json`
Good: `_text_or_fallback`, `_assign_hypothesis_id`, `json.dumps` (just call it directly)

**5. Use inline comments for non-obvious logic.**

If a block of code does something that requires domain knowledge to
understand, add a short comment above it. Example:
```python
# Score formula: 35% novelty + 30% plausibility + 35% testability
overall = 0.35 * novelty + 0.30 * plausibility + 0.35 * testability
```

**6. When modifying existing V2 code during V3 work, opportunistically
improve the docstrings and comments of the functions you touch.**

Do NOT refactor the logic or rename existing functions (that risks breaking
things). But DO replace useless docstrings like "Internal helper to X" with
meaningful ones when you're already editing that function for V3 changes.

### Known V2 Band-Aids (context for Codex)

These fallback mechanisms exist in crew_v2_postprocess.py. They should fire
less often as V3 improves prompt quality and model capability:

1. `_hydrate_summa_triplets()` — inserts placeholder text like
   "Objection 1 was not explicitly provided." Better prompts and a stronger
   model should reduce this.

2. `_fallback_grounded_citations()` — grabs top 3 papers from Semantic Scholar
   when the LLM fails to cite grounded papers. Better retrieval and explicit
   citation instructions should reduce this.

3. `_build_summa_rendering()` — fallback renderer that fires when the LLM's
   rendering fails validation. A stronger model should reduce this.

Do NOT remove these fallbacks. They are safety nets. Just let them fire less
often naturally.

### Cost Budget

- Current V2: ~$0.02/run (gpt-4o-mini everywhere, 20 questions ~ $0.40 per benchmark)
- With model routing: ~$0.10-0.30/run (gpt-4o for 3 stages, gpt-4o-mini for 3)
- Full benchmark with routing: ~$2-6 per 20-question run
- Budget envelope: keep single-question cost under $0.50 and full benchmark under $10.

---

## Codex Final Adjustments (Decision-Theoretic Simplification)

This section resolves a few internal contradictions in the comments above and
sets a simpler, safer V3 execution plan.

### Viability Verdict

V3 is viable and doable without making the codebase unmanageable, as long as we
keep changes surgical and stage-local. We should proceed.

### What We Accept As-Is

- Add **Priority 0 model routing** (`CREATIVE_MODEL`) before other V3 work.
- Keep **agent count unchanged**.
- Keep the **2-work-package structure** (WP7 infrastructure/evidence, WP8 quality/calibration).
- Emphasize readability: minimal helpers, clear names, meaningful docstrings.

### Required Corrections Before Implementation

1. **Do not hard-drop all short/empty-abstract papers unconditionally.**
   - A strict abstract filter can hurt math/CS coverage where metadata is sparse.
   - Use a soft rule: prefer abstract-rich papers, but keep sparse papers when
     retrieval pool is small.

2. **Do not rely on citation-count sorting alone.**
   - Pure citation sort biases old canonical papers and can bury newer relevant work.
   - Use a lightweight composite ordering:
     - has_abstract (yes first),
     - citation_count (desc),
     - year (desc).

3. **If `_metadata` is added to payload, schema must explicitly allow it.**
   - Current root schema uses `additionalProperties: false`.
   - Therefore `_metadata` cannot be added unless schema is updated first.

4. **Keep evaluation changes minimal for V3 implementation.**
   - No new benchmark infrastructure.
   - We can add helper-level tests and existing unit-test coverage only.

### Complexity Budget (Hard Constraints)

- No new agents.
- No new orchestration files beyond existing V2 split.
- No broad refactor during V3 feature work.
- Each WP must remain understandable in one pass by reading changed files only.

### Final V3 Execution Order

1. **WP7 (Priority 0 + Priority 1):**
   - model routing + retrieval/query improvements.
2. **WP8 (Priority 2 + 3 + 4 + 5-lite):**
   - mechanism slots, specificity checks, ranker calibration, optional metadata
     only if schema is updated in the same WP.
3. Run `summa-benchmark-compare` once at the end of both WPs.

### Go / No-Go For Starting V3

**GO** — with the corrections above.  
This path keeps rigor intact while controlling complexity and preserving readability.
