#!/usr/bin/env python3
"""Mint a local dev analyst bearer token for services/api.

Placeholder until the real OIDC identity provider decision is made
(plan.md §7.2) -- see docs/pre-production-security-todo.md. There is no
user directory; any UUID can be used as the analyst id.

Usage:
    python scripts/mint_dev_token.py --org <organization_id> --analyst <analyst_id> --role analyst
"""

import argparse
import sys
import uuid
from pathlib import Path

import jwt


def _load_env_value(key: str) -> str | None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True, help="organization_id (UUID)")
    parser.add_argument("--analyst", default=None, help="analyst_id (UUID); random if omitted")
    parser.add_argument("--role", default="analyst", choices=["analyst", "lead"])
    args = parser.parse_args()

    secret = _load_env_value("API_JWT_SECRET")
    audience = _load_env_value("API_JWT_AUDIENCE") or "fincrime-api"
    if not secret:
        print("API_JWT_SECRET not found in .env", file=sys.stderr)
        return 1

    analyst_id = args.analyst or str(uuid.uuid4())
    token = jwt.encode(
        {"sub": analyst_id, "org": args.org, "role": args.role, "aud": audience},
        secret,
        algorithm="HS256",
    )
    print(token)
    print(f"# analyst_id={analyst_id} org={args.org} role={args.role}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
