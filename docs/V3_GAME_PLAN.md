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
