"""Contribution-only setup checks. Author: Tishneet."""
from pathlib import Path
import tempfile
import unittest

from scripts.run_integration import check_dependencies


class ContributionSetupTests(unittest.TestCase):
    def test_missing_team_code_has_clear_integration_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SystemExit) as error:
                check_dependencies(directory)
            self.assertIn("backend/api/handlers.py", str(error.exception))
            self.assertIn("backend/core/simulator.py", str(error.exception))
            self.assertIn("docs/integration.patch", str(error.exception))

    def test_dependencies_checked_without_importing_or_running_them(self):
        with tempfile.TemporaryDirectory() as directory:
            for relative in ("backend/api/handlers.py", "backend/core/simulator.py"):
                target = Path(directory) / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("raise AssertionError('must not execute in prerequisite check')")
            check_dependencies(directory)


if __name__ == "__main__":
    unittest.main()
