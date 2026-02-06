# Summa Technologica: V2 Roadmap (Final Spec)

## 1) V1 status

V1 is a working prototype that:

- takes a user question,
- generates a Summa-shaped response,
- uses CrewAI YAML configuration,
- validates output structure.

V1 proves feasibility, not research-grade hypothesis quality.

## 2) V2 objective

V2 upgrades from "structured argument generator" to "grounded hypothesis engine" while preserving Summa identity.

V2 must produce:

- multiple distinct candidate hypotheses,
- grounded citations from Semantic Scholar,
- falsifiable predictions and minimal experiments,
- robust ranking,
- at least one full Summa block in every output.

## 3) Final architecture and agent-count decision

### Decision

Use **6 agents** for V2. This is the best complexity/performance tradeoff.

### Why 6 is optimal for V2

- Below 6, required reasoning functions get over-merged (framing, retrieval synthesis, critique, ranking, composition), which increases cognitive load per call and lowers reliability.
- Above 6, latency, cost, and handoff failures increase without proportional quality gain.
- 6 cleanly maps to the mandatory responsibilities and keeps the pipeline auditable.

### 6-agent pipeline

1. `ProblemFramerAgent`
2. `LiteratureScoutAgent`
3. `HypothesisGeneratorAgent`
4. `CriticAgent`
5. `RankerAgent`
6. `SummaComposerAgent`

No separate LLM `QualityGateAgent`; quality gates are programmatic in Python.

## 4) Output contracts (V2)

V2 JSON output contains:

- `question`
- `domain`
- `hypotheses[]` with:
  - `id`, `title`, `statement`
  - `novelty_rationale`, `plausibility_rationale`, `testability_rationale`
  - `falsifiable_predictions[]`
  - `minimal_experiments[]`
  - `objections[]` (exactly 3)
  - `replies[]` (exactly 3)
  - `citations[]`
  - `pairwise_record`
  - `scores` (derived values)
- `ranked_hypothesis_ids[]`
- `summa_rendering`
- optional `error` for partial-failure returns

Schema file: `schemas/hypothesis_schema.json` (programmatically enforced).

## 5) Retrieval subsystem (hard constraints)

- Backend: Semantic Scholar API only.
- Retrieval per run uses two queries:
  - raw user question,
  - refined query from `ProblemFramerAgent`.
- Merge and deduplicate by Semantic Scholar paper ID.
- `LiteratureScoutAgent` gets top evidence as structured JSON.

Citation validity rules:

- each citation must include title, authors, year, and paper ID or DOI,
- unverifiable citations are rejected,
- if retrieval fails/empty: emit `no grounded citations found`.

## 6) Hypothesis generation and distinctness enforcement

`HypothesisGeneratorAgent` outputs target 5 hypotheses (soft target), each with test plan and falsification path.

`CriticAgent` must output:

- objections and failure modes,
- a pairwise distinctness matrix across hypotheses,
- per non-distinct pair: which to keep and which to collapse, with rationale.

Distinctness axes (at least one must differ for every surviving pair):

- causal mechanism,
- empirical domain,
- theoretical framework.

If fewer than 3 distinct hypotheses survive, rerun generation once with stronger diversity constraints.

## 7) Ranking method

Use pairwise comparison, not direct absolute scoring by the LLM.

`RankerAgent` outputs pairwise judgments for novelty, plausibility, and testability. Python code then:

1. computes ranking from pairwise wins,
2. derives displayable 1-5 scores,
3. computes overall score using:
   - novelty `0.35`
   - plausibility `0.30`
   - testability `0.35`.

The 1-5 rubric anchors remain mandatory in `eval/rubric.md` and ranker prompts.

## 8) Summa rendering rules (identity lock)

Every V2 output must include at least one full Summa block with:

- question,
- three objections,
- `On the contrary`,
- `I answer that`,
- three replies.

Dialectical mapping:

- for ranked #1, `On the contrary` is derived from ranked #2,
- if only one hypothesis survives, derive from strongest critic objection,
- with `--top 3`, render 3 Summa blocks separated by `---`.

CLI behavior:

- default `--mode v1`,
- V2 enabled by `--mode v2`,
- `--top` supports `1` or `3`.

## 9) Programmatic validation and failure handling

Programmatic validation stack:

- `jsonschema` validation against `schemas/hypothesis_schema.json`,
- citation integrity checks (paper ID/DOI rules),
- Summa-structure checks.

Retry policy:

- each agent stage retries once on parse/validation failure with explicit error context,
- if retry fails, terminate gracefully with partial result.

Partial failure output includes:

- all successful stage outputs,
- `error.stage`,
- `error.message`,
- `error.retry_attempted`,
- any hypotheses produced so far.

## 10) Benchmark-first execution order (final)

1. Create `eval/benchmarks.yaml` (20 prompts: 5 each for physics, mathematics, biology, CS).
2. Create `eval/rubric.md` with rubric anchors.
3. Run V1 on full benchmark set and store baseline outputs.
4. Add CLI flags: `--mode`, `--top` (default `--mode v1`).
5. Add `schemas/hypothesis_schema.json` and validators.
6. Implement Semantic Scholar tool + `LiteratureScoutAgent` integration.
7. Implement remaining V2 agents and crew orchestration.
8. Run V2 on same benchmark set and compare to V1 baseline.
9. Tune prompts/flow only where benchmark metrics show regression.

## 11) Budget and latency guardrails

Ceilings:

- `gpt-4o-mini`: `< 5 min` and `< $0.10` per run,
- expensive-tier model: `< $1.00` per run.

Monitoring requirements:

- record per-stage latency,
- record per-stage token usage,
- estimate per-run cost in benchmark reports.

## 12) Acceptance criteria for V2

V2 is accepted only if all are met:

1. `>= 95%` schema-valid outputs.
2. `>= 90%` outputs include explicit falsifiable predictions.
3. `>= 80%` outputs include 3+ grounded citations or explicit `no grounded citations found` fallback.
4. Human rubric rating improves by `>= 1.0` vs V1 on novelty+testability composite.
5. Budget/latency ceilings are respected on benchmark runs.

## 13) Work packages for smooth implementation

### WP1: Evaluation baseline

- benchmark file,
- rubric file,
- baseline runner for V1.

### WP2: Contracts and validation

- V2 JSON schema,
- python validators,
- partial-failure error contract.

### WP3: Retrieval and grounding

- Semantic Scholar tool,
- dual-query merge/dedupe,
- citation verification.

### WP4: V2 crew and prompts

- 6-agent YAML configs,
- stage outputs as structured JSON,
- retry-once orchestration logic.

### WP5: Ranking and rendering

- pairwise rank computation,
- derived scores,
- Summa rendering rules with `--top` behavior.

### WP6: Benchmark comparison and tuning

- V1 vs V2 report,
- targeted prompt/logic tuning,
- final go/no-go decision.






## COMMENTS (v2, supersedes all previous comments)

These comments override and replace all prior review comments. They must be treated as hard constraints on the V2 implementation. Where these comments conflict with sections 3, 11, 12, or 13 above, these comments take precedence.

### C1. Reduce the agent count from 8 to 6

Section 3 proposes 8 agents. This is too many. Each sequential agent adds 10-30 seconds of latency, increases the probability of a parsing failure at handoff, and increases token cost. Two of the proposed agents can be merged without any loss of rigor.

Merge 1: `HypothesisGeneratorAgent` and `TestDesignerAgent` become a single `HypothesisGeneratorAgent`. A hypothesis without a falsification path is incomplete. Asking a separate agent to retrofit test plans onto hypotheses it did not write introduces lossy handoff. The generator must produce each hypothesis together with its falsifiable predictions and minimal experiments in one pass.

Merge 2: `SummaComposerAgent` and `QualityGateAgent` become a single `SummaComposerAgent`. Schema validation and citation verification must be done programmatically in Python code (using `jsonschema` and checking Semantic Scholar paper IDs), not by asking a second LLM to review the first LLM's output. LLM-based format checking is unreliable. The programmatic validation runs after the agent finishes, as a Python function, not as a separate agent call.

The V2 agent pipeline is therefore:

1. `ProblemFramerAgent` - scope, definitions, constraints, two possible thesis directions
2. `LiteratureScoutAgent` - retrieval via Semantic Scholar API, evidence summary
3. `HypothesisGeneratorAgent` - N diverse hypotheses, each with falsifiable predictions and minimal experiments
4. `CriticAgent` - objections, failure modes, distinctness checking, collapses non-distinct hypotheses
5. `RankerAgent` - scores each hypothesis, produces ranked list
6. `SummaComposerAgent` - renders top hypothesis (or top 3) as Summa-format output, validated programmatically

This is 6 LLM calls instead of 8. It respects the budget ceiling in section 11.6 more easily. It reduces the error surface. It loses nothing, because the merged responsibilities were tightly coupled to begin with.

Sections 3, 11.7, 11.9, and 11.10 must be read as applying to this 6-agent architecture, not the original 8-agent one. Specifically: section 11.9's requirement for programmatic `jsonschema` validation is now a Python function called after `SummaComposerAgent` finishes, not a separate agent. Section 11.7's retry logic applies to all 6 agents.

### C2. Benchmarks must be built before V2 agents, not after

Section 13 puts benchmarks at step 5 of 6. This is backwards. Without a baseline measurement of V1, there is no way to know whether V2 is better.

The correct implementation order is:

1. Write `eval/benchmarks.yaml` with 20 benchmark questions (5 per domain as specified in section 11.5) and write `eval/rubric.md` with the scoring rubric from section 11.3.
2. Run V1 against all 20 benchmarks. Record outputs. Manually score a subset using the rubric. This is the baseline.
3. Add `--mode` and `--top` CLI flags with `--mode v1` as default (section 11.8).
4. Create `schemas/hypothesis_schema.json`.
5. Implement the Semantic Scholar tool and `LiteratureScoutAgent`.
6. Implement the remaining V2 agents and the V2 crew.
7. Run V2 against the same 20 benchmarks. Compare against V1 baseline using the metrics in section 6.

This order ensures that every engineering decision in steps 5-6 can be validated against a fixed benchmark. It also means the benchmark infrastructure gets tested early, when it is cheapest to fix.

Section 13 must be replaced with this ordering.

### C3. Scoring should use pairwise comparison, not absolute numerical ratings

Section 11.3 defines a 1-5 rubric for novelty, plausibility, and testability. The rubric anchors are good and should be kept in `eval/rubric.md` for human evaluation. But the `RankerAgent` should not be asked to produce absolute numerical scores on a 1-5 scale.

The problem: LLMs are poor at consistent numerical scoring. They exhibit central tendency bias (everything gets a 3 or 4), anchoring effects (first hypothesis scored sets the scale), and position bias (hypotheses listed first or last get different scores than middle ones). This is well-documented in the LLM-as-judge literature.

The solution: the `RankerAgent` should use pairwise comparison. For each pair of hypotheses, ask: "Which hypothesis is more novel? Which is more plausible? Which is more testable?" Then derive a ranking from pairwise wins (simple win-count or Bradley-Terry if needed). This produces a reliable ordering even when absolute calibration is poor.

Implementation: if there are N hypotheses, there are N*(N-1)/2 pairs. For 5 hypotheses, that is 10 comparisons across 3 dimensions, which is 30 comparison questions. These can all be included in a single prompt to the `RankerAgent` to keep it to one LLM call. The agent outputs a JSON array of pairwise results, and a Python function computes the final ranking and derives approximate 1-5 scores (by mapping rank position to the rubric scale) for display purposes.

The 1-5 rubric from section 11.3 is still used for two things: (a) as qualitative guidance in the pairwise comparison prompt ("when judging novelty, consider that a 1 means X and a 5 means Y"), and (b) for human evaluation in the benchmark harness. But the `RankerAgent` does not output raw 1-5 numbers. It outputs pairwise judgments.

The overall score formula `0.35*novelty + 0.30*plausibility + 0.35*testability` from section 11.3 still applies, but is computed over the derived scores, not over raw LLM ratings.

### C4. The retrieval backend specification is confirmed but needs one addition

Section 11.1 correctly specifies Semantic Scholar as the retrieval backend. This comment confirms that requirement and adds one implementation detail.

The Semantic Scholar search tool must issue two separate queries per run: (a) a direct keyword query using the user's question, and (b) a refined query generated by the `ProblemFramerAgent` based on its restatement of the problem. This is because user questions are often colloquial and may not match the terminology used in academic papers. The two result sets are merged and deduplicated by paper ID before being passed to downstream agents. This doubles retrieval coverage at minimal cost (two HTTP requests, no additional LLM calls).

All other requirements from section 11.1 remain unchanged: citation must include title, authors, year, and paper ID or DOI. No unverifiable citations. If the API returns nothing, output "no grounded citations found."

### C5. Hypothesis distinctness enforcement is confirmed with one clarification

Section 11.2 correctly specifies distinctness requirements. This comment confirms them and adds one clarification.

The `CriticAgent` must output an explicit distinctness matrix: for each pair of hypotheses, state which distinctness axis (causal mechanism, empirical domain, or theoretical framework) differentiates them, or state "NOT DISTINCT" if none does. This matrix must be included in the `CriticAgent`'s structured output so that the collapse decision is traceable and auditable, not implicit.

If the `CriticAgent` marks a pair as "NOT DISTINCT," it must also state which hypothesis to keep (the one with a more specific mechanism) and which to collapse. The kept hypothesis may incorporate the strongest elements of the collapsed one.

### C6. The Summa-hypothesis mapping is confirmed with one constraint

Section 11.4 correctly specifies the mapping. This comment confirms it and adds one constraint.

The `on_the_contrary` for the top-ranked hypothesis must be derived from the second-ranked hypothesis. Specifically: the `SummaComposerAgent` prompt must instruct the agent to frame the counter-thesis as the core claim of the second-ranked hypothesis. This is what makes the Summa format dialectical rather than monological. If there is only one surviving hypothesis after the `CriticAgent` collapses non-distinct ones, the `on_the_contrary` should be derived from the strongest objection raised by the `CriticAgent`.

When `--top 3` is used, the `on_the_contrary` for hypothesis ranked #1 comes from hypothesis #2, the `on_the_contrary` for #2 comes from #1, and the `on_the_contrary` for #3 comes from #1. Each Summa block is separated by `---` in markdown output.

### C7. Error handling applies to 6 agents, not 8

Section 11.7 is confirmed but must be read against the 6-agent architecture from C1 above. The retry-once-then-fail-gracefully policy applies to all 6 agent stages. The programmatic `jsonschema` validation that runs after `SummaComposerAgent` is not a separate agent, so its failure triggers a retry of `SummaComposerAgent` itself (as section 11.9 already specifies).

The partial result returned on terminal failure must include: all successfully completed agent outputs up to the failure point, the error field (`error.stage`, `error.message`, `error.retry_attempted`), and any hypotheses generated so far even if they have not been scored or rendered into Summa format. This gives the user something to work with rather than nothing.

### C8. Cost ceiling is tighter with 6 agents

Section 11.6 specifies a $0.10 ceiling for `gpt-4o-mini` and $1.00 for expensive models. With 6 agents instead of 8, these ceilings should be achievable with margin. But the budget must now also account for the pairwise comparison approach in C3, which puts more text into the `RankerAgent` prompt.

Estimated token budget per V2 run with `gpt-4o-mini` at 6 agents:
- ProblemFramer: ~500 input + ~300 output
- LiteratureScout: ~800 input + ~1500 output (includes API results)
- HypothesisGenerator: ~2000 input + ~2000 output
- Critic: ~3000 input + ~1500 output
- Ranker: ~3000 input + ~1000 output (pairwise comparisons)
- SummaComposer: ~3000 input + ~1500 output

Total: roughly 12,300 input + 7,800 output tokens. At `gpt-4o-mini` pricing ($0.15/1M input, $0.60/1M output), that is approximately $0.007 per run. Well within the $0.10 ceiling. The latency ceiling of 5 minutes should also hold with 6 sequential calls.

These are estimates. The benchmark harness must record actual token counts and costs per run to validate them.

### C9. The Summa format is the identity of this project

This restates section 11.10 with stronger emphasis. The Summa disputational format is what separates this tool from every other AI brainstorming wrapper. Without it, the project is just another hypothesis generator. The name "Summa Technologica" is a direct reference to the Summa Theologica. The format is not optional, not a legacy artifact, and not a suggestion. It is the core product.

Every V2 output must contain at minimum one complete Summa block: the question, three objections, an "on the contrary" derived from a competing hypothesis or the strongest objection, an "I answer that" presenting the thesis, and three replies that directly address the objections. This structure must be present in both the markdown output and the JSON output (as the `summa_rendering` field).

If the `SummaComposerAgent` produces output without this structure, programmatic validation must catch it and trigger a retry. This is a schema-level constraint, not a prompt-level hope.

### C10. Section 14 should be removed

Section 14 ("Confidence statement") adds no information. "Yes, this abstraction level is manageable" and "the architecture is technically feasible" are assertions without evidence or content. Remove this section. The roadmap should contain specifications and constraints, not reassurances.
