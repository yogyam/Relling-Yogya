"""Run every verification suite in one command:

    python check_all.py

Smoke (scene compiles + physics sane), episode randomization properties
(bit-identical replay, variation, 200-seed sanity, tip-rate), and the judge's
10-fixture exam. Exits non-zero on the first failure.
"""

import subprocess
import sys

SUITES = ["smoke.py", "check_episodes.py", "check_judge.py"]


def main() -> None:
    for suite in SUITES:
        print(f"=== {suite} ===")
        result = subprocess.run([sys.executable, suite])
        if result.returncode != 0:
            raise SystemExit(f"FAILED: {suite}")
    print("\nCHECK ALL OK")


if __name__ == "__main__":
    main()
