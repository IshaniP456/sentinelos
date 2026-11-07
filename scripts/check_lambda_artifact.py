"""Verify SAM ships only importable runtime content. Author: Tishneet."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    artifact = Path(sys.argv[1]).resolve()
    for name in (".git", ".venv", "ProjectCollateral.pdf", "graph-engineering-codex", "frontend"):
        assert not (artifact / name).exists(), "Unexpected development content: " + name
    assert not (artifact / "backend" / "tests").exists()
    assert (artifact / "backend" / "ai" / "plan.schema.json").is_file()
    env = dict(os.environ, PYTHONPATH=str(artifact))
    subprocess.check_call([sys.executable, "-c",
                           "import backend.workflows.aws, backend.ai.providers, backend.workflows.service; "
                           "print('Packaged Lambda modules import successfully')"], cwd=artifact, env=env)
    print("SAM artifact excludes local development files")


if __name__ == "__main__":
    main()
