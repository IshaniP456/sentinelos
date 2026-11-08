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
    if (artifact / "backend" / "security" / "gateway.py").is_file():
        subprocess.check_call([sys.executable, "-c", """
from unittest.mock import patch
with patch('boto3.client', side_effect=AssertionError('Gateway construction must not call AWS')):
    from backend.security.gateway import create_gateway
    gateway = create_gateway(None)
    assert gateway.name == 'LAMBDA_GATEWAY'
    assert gateway._signing_key is None
print('Packaged team gateway imports and constructs without AWS or signing key')
"""], cwd=artifact, env=env)
    print("SAM artifact excludes local development files")


if __name__ == "__main__":
    main()
