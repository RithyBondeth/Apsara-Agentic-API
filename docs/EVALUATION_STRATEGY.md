# Coding-agent evaluation strategy

Apsara separates deterministic CI scoring from optional live model evaluation.
CI never needs an API key; a live run writes replayable evidence that can be
scored again without spending tokens.

## Test pyramid

| Layer | Purpose | Target |
|---|---|---|
| Unit | Scoring, manifests, path boundaries, rollback conflicts | Every scoring and recovery branch |
| Integration | Multi-file turns, command snapshots, interrupted runs, CLI dispatch | All terminal states and mutation types |
| Live benchmark | End-to-end model behavior in disposable repositories | Python, TypeScript, Go, and Rust |

The core suite measures the properties that matter for a coding agent:

- 50 points: the repository's independent verification command passes;
- 15 points: the agent reaches a completed state;
- 15 points: changes stay within the allowed production files;
- 10 points: tool calls stay within the case budget;
- 10 points: provider-reported tokens stay within the case budget.

A case must pass verification, avoid unexpected edits, and score at least 80.
Editing tests therefore cannot turn a broken solution into a passing result.

## Running the suite

The fixtures intentionally start with failing tests. A live run uses provider
tokens and copies every fixture beneath `.apsara/benchmarks/`:

```bash
apsara eval evals/coding-core.json --live --model opencode/big-pickle
```

Each run produces `results.json`, per-case run journals, turn checkpoints, and
the raw event stream. Re-score the evidence offline with:

```bash
apsara eval evals/coding-core.json --results .apsara/benchmarks/<run>/results.json
```

A missing language runtime is recorded as `unavailable`, never mistaken for a
passing verification. Use the JSON suite format to add larger repositories or
provider-specific token and tool-call budgets.

## Release coverage targets

- 100% of transaction restoration and scoring decision branches have tests.
- All offline tests pass on Python 3.10–3.13, macOS and Ubuntu.
- Windows smoke packaging remains green.
- Before a release candidate, run the live core suite with the default model
  and retain its `results.json` as release evidence.

## Known gaps

The bundled fixtures are small and deterministic, so they test agent mechanics
more than long-horizon architecture. Production release evaluation should add
larger pinned open-source repositories, flaky-test detection, repeated trials,
and quality review for solutions that pass tests but degrade maintainability.
