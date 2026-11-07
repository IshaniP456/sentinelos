"""Controlled SAM artifact assembly. Author: Tishneet.

Only backend source and pinned runtime dependencies enter the artifact. Local
virtualenvs, credentials, PDFs, frontend, tests, and Graph skills never enter it.
"""
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    if (platform.system() != "Linux" or platform.machine().lower() not in {"aarch64", "arm64"}
            or sys.version_info[:2] != (3, 12)):
        raise RuntimeError("Lambda requires Linux ARM64/Python3.12; run make aws-build using the tooling container.")
    root = Path(__file__).resolve().parents[1]
    destination = Path(os.environ["ARTIFACTS_DIR"]).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root / "backend", destination / "backend", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc", "*.md",
                                                 "Dockerfile", "requirements*.txt", "template.yaml", ".env*"))
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                           "--no-compile", "--no-cache-dir", "--target", str(destination),
                           "-r", str(root / "backend" / "requirements-runtime-lock.txt")])
    print("SAM artifact assembled with backend source and pinned runtime dependencies")


if __name__ == "__main__":
    main()
