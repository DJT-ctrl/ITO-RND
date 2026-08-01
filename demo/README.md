# Invite-only demo (Vercel)

The shareable Streamlit harness now lives in
**[intotheopen/dashboard-for-devs](https://github.com/intotheopen/dashboard-for-devs)**.

Deploy and invite-gate docs belong there (or a branch of that repo). This backend
repo only provides API, agents, pipelines, and Postgres.

## What the viewer gets

1. Open the Vercel URL for **dashboard-for-devs**
2. Enter the invite password
3. Use the Streamlit ops harness against a configured backend

They do **not** need git, Python, or Docker locally.

## Backend for the demo

Point the dashboard deploy at a running backend (or embed editable backend in
the dashboard image build). Required for live pages:

- `DATABASE_URL`
- `GEMINI_API_KEY` / `GOOGLE_API_KEY`
- Apify / LinkedIn secrets only if scrapers will run in the demo

## Local invite gate check

From the **dashboard-for-devs** checkout (with this backend on `PYTHONPATH` /
editable install):

```bash
DEMO_INVITE_PASSWORD='test' streamlit run dashboard/app.py
```

Firebase seed script remains here if you use Firestore for invite rotation:

```bash
python scripts/seed_demo_invite.py --password 'your-shared-password'
```
