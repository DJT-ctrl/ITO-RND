#!/usr/bin/env python3
"""Seed Firestore demo_invites/shared for the invite-only Vercel demo.

Requires:
  FIREBASE_PROJECT_ID
  FIREBASE_SERVICE_ACCOUNT_JSON  (JSON string)  OR  GOOGLE_APPLICATION_CREDENTIALS

Usage:
  python scripts/seed_demo_invite.py --password 'shared-secret'
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--password", required=True, help="Shared invite password")
    parser.add_argument(
        "--project",
        default=os.getenv("FIREBASE_PROJECT_ID", ""),
        help="Firebase project id (or set FIREBASE_PROJECT_ID)",
    )
    args = parser.parse_args()

    project_id = (args.project or "").strip()
    if not project_id:
        print("FIREBASE_PROJECT_ID / --project is required", file=sys.stderr)
        return 1

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError:
        print("Install firebase-admin: pip install -r requirements-demo.txt", file=sys.stderr)
        return 1

    if not firebase_admin._apps:
        cred_json = (os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON") or "").strip()
        if cred_json:
            cred = credentials.Certificate(json.loads(cred_json))
            firebase_admin.initialize_app(cred, {"projectId": project_id})
        else:
            firebase_admin.initialize_app(options={"projectId": project_id})

    db = firestore.client()
    db.collection("demo_invites").document("shared").set(
        {"password": args.password.strip()},
        merge=True,
    )
    print(f"Wrote demo_invites/shared on project {project_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
