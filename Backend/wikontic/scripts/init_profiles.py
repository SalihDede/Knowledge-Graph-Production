"""Initialize one or more Wikontic runtime profiles sequentially.

Profiles are read from WIKONTIC_PROFILES as a comma-separated list. Existing
ontology data is resumed and user triplet collections are never dropped.
"""

from __future__ import annotations

import os
import subprocess
import sys


def configured_profiles() -> list[str]:
    raw = os.getenv("WIKONTIC_PROFILES", "en__contriever")
    profiles = list(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
    if not profiles:
        raise SystemExit("WIKONTIC_PROFILES must contain at least one profile")
    return profiles


def main() -> None:
    profiles = configured_profiles()
    for index, profile in enumerate(profiles, start=1):
        print(f"[{index}/{len(profiles)}] Initializing Wikontic profile: {profile}", flush=True)
        subprocess.run(
            [sys.executable, "init_dbs.py", "--profile", profile, "--resume"],
            check=True,
        )
    print("All configured Wikontic profiles are ready.", flush=True)


if __name__ == "__main__":
    main()
