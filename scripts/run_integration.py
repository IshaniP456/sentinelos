"""Explicit integration entry point after the team merge. Author: Tishneet."""
import argparse
from pathlib import Path
import runpy
import subprocess
import sys


def check_dependencies(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    required = ("backend/api/handlers.py", "backend/core/simulator.py")
    missing = [path for path in required if not (root / path).is_file()]
    if missing:
        raise SystemExit("Integration dependencies missing: " + ", ".join(missing)
                         + ". Merge Ishani's API and Mariam's simulator first, then review/apply docs/integration.patch.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "worker", "api", "test"))
    args = parser.parse_args()
    check_dependencies()
    if args.operation == "worker":
        runpy.run_module("backend.workflows.worker", run_name="__main__")
    elif args.operation == "api":
        runpy.run_module("backend.workflows.local_api", run_name="__main__")
    elif args.operation == "test":
        raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "backend/tests", "-q"]))
    else:
        print("Team dependencies present; review docs/integration.patch before starting the workflow API.")


if __name__ == "__main__":
    main()
