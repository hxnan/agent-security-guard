import importlib
import json
from pathlib import Path
import tempfile
import unittest


VALID_RESULT = {
    "schema_version": "1.0",
    "risk": False,
    "decision": "allow",
    "severity": "none",
    "category": "benign",
    "summary": "正常查询",
    "confidence": 0.9,
    "evidence": ["git status"],
    "rule_hits": [],
    "model_version": "smoke-target-v1",
    "policy_version": "policy-v1",
}


class AdapterSmokeTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("guard.adapter_smoke")
        except ModuleNotFoundError:
            self.fail("guard.adapter_smoke is missing")

    def test_extracts_first_json_object_with_surrounding_text(self):
        api = self.api()
        text = "prefix\n" + json.dumps(VALID_RESULT, ensure_ascii=False) + "\nsuffix"
        self.assertEqual(api.extract_first_json_object(text), VALID_RESULT)

    def test_braces_inside_json_strings_do_not_break_extraction(self):
        api = self.api()
        value = dict(VALID_RESULT, evidence=["python -c \"print('{}')\""])
        text = "note " + json.dumps(value, ensure_ascii=False) + " trailing"
        self.assertEqual(api.extract_first_json_object(text), value)

    def test_missing_or_malformed_json_is_rejected(self):
        api = self.api()
        for text in ("no object", "prefix {broken json}"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(api.AdapterSmokeError, "JSON object"):
                    api.extract_first_json_object(text)

    def test_generated_result_must_match_guard_contract(self):
        api = self.api()
        parsed = api.validate_generated_result(json.dumps(VALID_RESULT, ensure_ascii=False))
        self.assertEqual(parsed.category.value, "benign")

        invalid = dict(VALID_RESULT, summary="x" * 31)
        with self.assertRaisesRegex(api.AdapterSmokeError, "GuardResult"):
            api.validate_generated_result(json.dumps(invalid))

    def test_report_is_written_deterministically(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "report.json"
            api.write_adapter_report(path, {"valid": True, "raw_text": "{}"})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"raw_text": "{}", "valid": True},
            )

    def test_preflight_requires_weight_config_metrics_and_manifest(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            adapter = output / "adapter"
            adapter.mkdir()
            required = {
                adapter / "adapter_config.json": "{}",
                adapter / "adapter_model.safetensors": "weights",
                output / "training_manifest.json": json.dumps(
                    {"method": "qlora-smoke", "data_version": "smoke-v1"}
                ),
                output / "training_metrics.json": "{}",
            }
            for path, content in required.items():
                path.write_text(content, encoding="utf-8")

            manifest = api.validate_adapter_artifacts(adapter)
            self.assertEqual(manifest["method"], "qlora-smoke")

            (output / "training_metrics.json").unlink()
            with self.assertRaisesRegex(api.AdapterSmokeError, "training_metrics"):
                api.validate_adapter_artifacts(adapter)

    def test_runtime_load_failure_is_wrapped_without_dependency_traceback(self):
        api = self.api()

        class BrokenAutoTokenizer:
            @staticmethod
            def from_pretrained(*args, **kwargs):
                raise ValueError("corrupt tokenizer")

        class Transformers:
            AutoTokenizer = BrokenAutoTokenizer

        with self.assertRaisesRegex(api.AdapterSmokeError, "could not load adapter runtime"):
            api.load_adapter_runtime(
                Path("adapter"),
                Path("model"),
                peft_module=object(),
                torch_module=object(),
                transformers_module=Transformers(),
            )

    def test_preflight_rejects_a_different_base_model(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            adapter = output / "adapter"
            adapter.mkdir()
            (adapter / "adapter_config.json").write_text("{}", encoding="utf-8")
            (adapter / "adapter_model.safetensors").write_text("weights", encoding="utf-8")
            (output / "training_metrics.json").write_text("{}", encoding="utf-8")
            (output / "training_manifest.json").write_text(
                json.dumps(
                    {
                        "method": "qlora-smoke",
                        "data_version": "smoke-v1",
                        "base_model_path": str(output / "trained-model"),
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(api.AdapterSmokeError, "base model"):
                api.validate_adapter_artifacts(adapter, output / "other-model")


if __name__ == "__main__":
    unittest.main()
