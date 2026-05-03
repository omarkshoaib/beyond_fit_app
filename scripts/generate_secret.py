"""Generate a random AUTH_SECRET_KEY for production.

Usage:
    python scripts/generate_secret.py
    python scripts/generate_secret.py --length 64
    python scripts/generate_secret.py --append-to .env
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--length", type=int, default=48,
                        help="Number of random bytes (output is base64url, ~1.33x longer). Default 48 = ~64 chars.")
    parser.add_argument("--append-to", type=str, default=None,
                        help="Append AUTH_SECRET_KEY=... to this file instead of printing.")
    args = parser.parse_args()

    secret = secrets.token_urlsafe(args.length)

    if args.append_to:
        path = Path(args.append_to)
        # Don't clobber an existing AUTH_SECRET_KEY line
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip().startswith("AUTH_SECRET_KEY="):
                    print(f"❌ {path} already has AUTH_SECRET_KEY. Refusing to add a duplicate.")
                    sys.exit(1)
        with path.open("a") as fh:
            fh.write(f"\nAUTH_SECRET_KEY={secret}\n")
        print(f"✅ Appended AUTH_SECRET_KEY to {path}")
    else:
        print(secret)


if __name__ == "__main__":
    main()
