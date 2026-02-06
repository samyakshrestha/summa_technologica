# V2 Evaluation Rubric

This rubric is the canonical reference for human evaluation in benchmark runs.

## Core dimensions

### Novelty (1-5)

- `1`: Restates a well-known position with no new angle.
- `3`: Combines known ideas in a way that is not standard but has been gestured at in existing literature.
- `5`: Proposes a mechanism, connection, or framing that does not appear in the top 50 Semantic Scholar results for the query.

### Plausibility (1-5)

- `1`: Contradicts well-established empirical results or mathematical theorems.
- `3`: Consistent with known evidence but lacks direct supporting data.
- `5`: Directly supported by multiple independent lines of evidence or derivable from accepted theory.

### Testability (1-5)

- `1`: No conceivable experiment or observation could distinguish this hypothesis from its negation.
- `3`: Testable in principle but requires resources or technology not currently available.
- `5`: Testable with a concrete experiment that could be run within one year using existing methods.

### Overall score

Use weighted average:

`overall = 0.35 * novelty + 0.30 * plausibility + 0.35 * testability`

## Binary checks

For each output, also mark:

- `summa_complete`: includes question, 3 objections, on the contrary, i answer that, and 3 replies.
- `falsifiable_predictions_present`: at least one concrete falsifiable prediction is present.
- `experiment_plan_present`: at least one minimal experiment is present.
- `grounded_citations_present`: citations include title, authors, year, and paper ID or DOI (or explicit fallback if none found).
- `bad_pattern_avoided`: does not match benchmark-specific known bad pattern.

## Human scoring workflow

1. Read the benchmark prompt and known bad pattern.
2. Read the model output once without scoring.
3. Score novelty, plausibility, and testability using anchors above.
4. Compute overall score with weighted formula.
5. Fill binary checks.
6. Add 1-3 sentences of qualitative rationale.

## Suggested reviewer template

```text
Benchmark ID:
Reviewer:
Date:

Novelty (1-5):
Plausibility (1-5):
Testability (1-5):
Overall:

summa_complete:
falsifiable_predictions_present:
experiment_plan_present:
grounded_citations_present:
bad_pattern_avoided:

Rationale:
```

