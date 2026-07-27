#!/usr/bin/env python3
"""Materialize an ephemeral runtime env file from AWS Secrets Manager (issue #13).

Examples:
  export ITO_AWS_SECRET_ID=ito/prod/runtime
  export AWS_REGION=eu-west-2
  python scripts/fetch_aws_secrets.py --out /run/ito/runtime.env

  # Dry-run against a local JSON file (no AWS call) — used by rotation tests:
  python scripts/fetch_aws_secrets.py --from-json deploy/secrets.example.json --out /tmp/ito-runtime.env
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.aws_secrets import (  # noqa: E402
    AwsSecretsError,
    fetch_secret_dict,
    missing_production_secrets,
    parse_secret_string,
    write_env_file,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(os.getenv("ITO_ENV_FILE", "/run/ito/runtime.env")),
        help="Destination env file (default: ITO_ENV_FILE or /run/ito/runtime.env)",
    )
    parser.add_argument(
        "--secret-id",
        default=os.getenv("ITO_AWS_SECRET_ARN") or os.getenv("ITO_AWS_SECRET_ID"),
        help="Secrets Manager name or ARN (or set ITO_AWS_SECRET_ID / ITO_AWS_SECRET_ARN)",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
        help="AWS region",
    )
    parser.add_argument(
        "--from-json",
        type=Path,
        default=None,
        help="Load secret JSON from a file instead of AWS (dry-run / tests)",
    )
    parser.add_argument(
        "--require-production-keys",
        action="store_true",
        help="Exit non-zero if required production secret keys are missing",
    )
    args = parser.parse_args(argv)

    try:
        if args.from_json is not None:
            secrets = parse_secret_string(args.from_json.read_text(encoding="utf-8"))
        else:
            if not args.secret_id:
                raise AwsSecretsError(
                    "Pass --secret-id or set ITO_AWS_SECRET_ID / ITO_AWS_SECRET_ARN"
                )
            secrets = fetch_secret_dict(args.secret_id, region_name=args.region)
    except AwsSecretsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.require_production_keys:
        missing = missing_production_secrets(secrets)
        if missing:
            print(
                "error: missing required production secret keys: " + ", ".join(missing),
                file=sys.stderr,
            )
            return 1

    path = write_env_file(secrets, args.out)
    print(f"wrote {len(secrets)} keys to {path} (mode 0600)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
