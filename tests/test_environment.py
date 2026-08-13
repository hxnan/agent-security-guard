import os
import tempfile
import unittest
from pathlib import Path

from guard.environment import REQUIRED_MODEL_FILES, resolve_model_path, validate_model_directory


class ModelEnvironmentTests(unittest.TestCase):
    def test_explicit_model_path_has_highest_priority(self):
        path = resolve_model_path("/models/explicit", {"AGENT_SECURITY_MODEL_PATH": "/models/env"})

        self.assertEqual(path, Path("/models/explicit"))

    def test_environment_model_path_is_used_when_explicit_path_is_absent(self):
        path = resolve_model_path(None, {"AGENT_SECURITY_MODEL_PATH": "/models/env"})

        self.assertEqual(path, Path("/models/env"))

    def test_default_model_path_matches_repository_convention(self):
        path = resolve_model_path(None, {})

        self.assertEqual(path, Path("models/base/Qwen2.5-1.5B-Instruct"))

    def test_complete_model_directory_has_no_missing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory)
            for file_name in REQUIRED_MODEL_FILES:
                (model_path / file_name).touch()

            self.assertEqual(validate_model_directory(model_path), [])

    def test_missing_model_files_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = validate_model_directory(Path(directory))

        self.assertEqual(missing, list(REQUIRED_MODEL_FILES))


if __name__ == "__main__":
    unittest.main()
