# Shared local data directory

Runtime artefacts for the corpus + validation pipelines live under **backend**
`data/` only:

| Path | Contents |
|------|----------|
| `data/raw/` | Scraper JSON collections |
| `data/processed/` | Analysed JSONL/CSV, caches |
| `data/embeddings/` | Gemini `.npy` matrices + sidecars |
| `data/validation/` | Collect / predict artefacts |
| `data/telemetry/` | Cost / run telemetry |
| `data/pipeline_manifest.json` | Bundle registry |

## dashboard-for-devs

The Streamlit ops UI must **symlink** its `data/` to this tree:

```bash
cd ../dashboard-for-devs
./scripts/ensure-shared-data.sh
```

Start scripts call that helper automatically. Do not keep a second local
`data/` copy in the dashboard repo — that is what caused “No vectorized
LinkedIn datasets found” when embeddings were written under the dashboard cwd.

## Path resolution

Backend writers resolve relative `data/…` paths with
`config.paths.resolve_data_path`, anchored at the backend package root
(`PROJECT_ROOT`), independent of process cwd. `processors.embedder.save_embeddings`
and related helpers follow that rule so Streamlit cannot split the tree again.
