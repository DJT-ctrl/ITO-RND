# Load testing (issue #21)

Reproducible HTTP load scenarios for `POST /api/v1/similar-posts` and
`POST /api/v1/evaluate`. See [`docs/ops/LOAD_BASELINE.md`](../../docs/ops/LOAD_BASELINE.md)
for the published baseline report and improvement plan.

## Quick start (latency stub — no Gemini/DB)

```bash
# terminal 1
python scripts/load/stub_api.py

# terminal 2
python scripts/load/run_load_test.py --scenario smoke --base-url http://127.0.0.1:8010
python scripts/load/run_load_test.py --scenario baseline --base-url http://127.0.0.1:8010 \
  --output /tmp/ito-load-baseline.json
```

## Against the real Compose API

```bash
docker compose up -d
# ensure GEMINI_API_KEY + ingested corpus — evaluate costs real provider calls

python scripts/load/run_load_test.py --scenario similar-posts-steady
python scripts/load/run_load_test.py --scenario evaluate-mixed
python scripts/load/run_load_test.py --scenario baseline --output /tmp/ito-load-live.json
```

## Scenarios

| Name | Purpose |
| ---- | ------- |
| `smoke` | 1 request per route |
| `similar-posts-steady` | 40 posts @ concurrency 8 |
| `evaluate-mixed` | 6 evaluates @ concurrency 2 |
| `baseline` | Combined profile for the published report |

Edit `scenarios.yaml` to change counts/concurrency. Override the target with
`--base-url`.
