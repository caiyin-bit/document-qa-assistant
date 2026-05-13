# Retrieval Evaluation Baselines

The fixture at `tests/fixtures/retrieval_eval.yaml` defines a small,
hand-curated corpus + query set. `scripts/eval_retrieval.py` ingests
the fixture into a disposable eval session, runs each query under
vector / trigram / hybrid retrieval, and writes R@1 / R@3 / R@5 / MRR
to a JSON baseline.

## Running

Requires `DATABASE_URL` set, project migrations applied, and the BGE
model accessible via sentence-transformers.

```bash
PYTHONPATH=. uv run python scripts/eval_retrieval.py \
    --json eval/baseline_$(date +%Y-%m-%d).json
```

Optional flags:

- `--modes vector hybrid` — restrict which modes to evaluate.
- `--top-k 10` — change the top-K cutoff used for both retrieval and
  the R@k computation.

## Workflow: before / after retrieval changes

1. On `main` (or the pre-change commit), generate the baseline:
   `python scripts/eval_retrieval.py --json eval/baseline_<DATE>.json`.
2. Apply your retrieval change on a branch.
3. Re-run the script writing a new file:
   `python scripts/eval_retrieval.py --json eval/<branch>_<DATE>.json`.
4. Diff the two JSON files. Hybrid R@5 must not regress on existing
   queries. If it does, investigate the cause before merging.

The fixture is small (6 queries) so per-mode averages move in coarse
steps — a single query going from miss to hit changes R@1 by ~0.17.
Treat the JSON as a trend signal, not a precision instrument.
