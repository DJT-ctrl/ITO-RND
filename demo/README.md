# Invite-only demo (Vercel)

Shareable host of the **existing** Streamlit test harness — same UI, no
rebuild for the viewer. Protected by a shared invite password.

## What the viewer gets

1. Open the Vercel URL
2. Enter the invite password
3. Use the same Streamlit harness as local (`dashboard/app.py`)

They do **not** need git, Python, or Docker.

## Host setup

### 1. Branch

```bash
git checkout invite-only-demo
```

### 2. Invite password (pick one)

**A. Env var (simplest)** — set on Vercel:

- `DEMO_INVITE_PASSWORD` = shared password you give the viewer

**B. Firebase (rotate without redeploy)** — set on Vercel:

- `DEMO_INVITE_USE_FIREBASE=true`
- `FIREBASE_PROJECT_ID=<your-project-id>`
- `FIREBASE_SERVICE_ACCOUNT_JSON=<service-account-json>`

Then seed Firestore:

```bash
python scripts/seed_demo_invite.py --password 'your-shared-password'
```

This writes `demo_invites/shared.password` in Firestore.

### 3. Deploy

```bash
vercel link   # create or link project, e.g. ito-invite-demo
vercel env add DEMO_INVITE_PASSWORD production
vercel deploy --prod
```

Vercel builds `Dockerfile.vercel` (Streamlit on `$PORT`).

### Optional backend env

Same as local if you want live pages (similarity, validation, etc.):

- `DATABASE_URL`
- `GEMINI_API_KEY` / `GOOGLE_API_KEY`
- Apify / LinkedIn secrets only if you will run scrapers in the demo

Without those, the harness still opens; data pages show the usual missing-config warnings.

## Local check of the gate

```bash
DEMO_INVITE_PASSWORD='test' streamlit run dashboard/app.py
```
