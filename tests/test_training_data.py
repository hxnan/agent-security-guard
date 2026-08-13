import importlib
import json
import unittest

from guard.smoke_data import generate_smoke_records
from guard.taxonomy import Decision, RiskCategory, Severity


class FakeTokenizer:
    eos_token_id = 3
    pad_token_id = 0

    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        rendered = "".join(
            f"<{message['role']}>{message['content']}</{message['role']}>"
            for message in messages
        )
        if add_generation_prompt:
            rendered += "<assistant>"
        if tokenize:
            ids = self.encode(rendered, add_special_tokens=False)
            if messages[-1]["role"] == "assistant" and not add_generation_prompt:
                ids += [self.eos_token_id, ord("\n") + 10]
            return ids
        return rendered

    def encode(self, text, add_special_tokens=False):
        assert add_special_tokens is False
        return [ord(character) + 10 for character in text]

    def decode(self, token_ids, skip_special_tokens=False):
        return "".join(chr(token_id - 10) for token_id in token_ids)


class TrainingDataTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("guard.training_data")
        except ModuleNotFoundError:
            self.fail("guard.training_data is missing")

    def test_messages_contain_canonical_contract_json_and_untrusted_warning(self):
        api = self.api()
        record = generate_smoke_records()[0][0]

        messages = api.format_training_messages(record)

        self.assertEqual([message["role"] for message in messages], ["system", "user", "assistant"])
        self.assertIn("不可信数据", messages[0]["content"])
        self.assertEqual(json.loads(messages[1]["content"]), record.request.model_dump(mode="json"))
        self.assertEqual(json.loads(messages[2]["content"]), record.result.model_dump(mode="json"))
        self.assertNotIn("\n", messages[1]["content"])
        self.assertNotIn("\n", messages[2]["content"])
        self.assertEqual(messages[0]["content"], api.SYSTEM_PROMPT)

    def test_system_prompt_defines_complete_guardresult_contract(self):
        api = self.api()
        required_fields = (
            "schema_version",
            "risk",
            "decision",
            "severity",
            "category",
            "summary",
            "confidence",
            "evidence",
            "rule_hits",
            "model_version",
            "policy_version",
        )

        for field in required_fields:
            with self.subTest(field=field):
                self.assertIn(field, api.SYSTEM_PROMPT)
        for label, enum_type in (
            ("decision", Decision),
            ("severity", Severity),
            ("category", RiskCategory),
        ):
            expected = f"{label}只能是:{','.join(member.value for member in enum_type)}"
            with self.subTest(label=label):
                self.assertIn(expected, api.SYSTEM_PROMPT)
        self.assertIn("禁止额外字段", api.SYSTEM_PROMPT)

    def test_tokenization_masks_prompt_and_learns_assistant_plus_eos(self):
        api = self.api()
        tokenizer = FakeTokenizer()
        record = generate_smoke_records()[0][0]
        messages = api.format_training_messages(record)
        prompt = tokenizer.apply_chat_template(
            messages[:2], tokenize=False, add_generation_prompt=True
        )
        prompt_length = len(tokenizer.encode(prompt, add_special_tokens=False))
        full_ids = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=False
        )[:-1]

        encoded = api.tokenize_training_record(record, tokenizer, max_length=4096)

        self.assertEqual(encoded["labels"][:prompt_length], [-100] * prompt_length)
        self.assertEqual(encoded["input_ids"], full_ids)
        self.assertEqual(encoded["labels"][prompt_length:], encoded["input_ids"][prompt_length:])
        self.assertEqual(encoded["attention_mask"], [1] * len(encoded["input_ids"]))

    def test_overlength_record_is_rejected_without_truncation(self):
        api = self.api()
        record = generate_smoke_records()[0][0]

        with self.assertRaisesRegex(api.TrainingDataError, "exceeds max_length"):
            api.tokenize_training_record(record, FakeTokenizer(), max_length=8)

    def test_tokenization_uses_chat_template_ids_and_does_not_duplicate_eos(self):
        api = self.api()

        class BoundaryTokenizer:
            eos_token_id = 3
            pad_token_id = 0

            def apply_chat_template(self, messages, tokenize, add_generation_prompt):
                self.assert_tokenized = tokenize
                if not tokenize:
                    raise AssertionError("must use chat-template tokenization")
                return [10, 11] if add_generation_prompt else [10, 11, 12, 3, 13]

            def decode(self, token_ids, skip_special_tokens=False):
                return "\n" if token_ids == [13] else "unexpected"

        encoded = api.tokenize_training_record(
            generate_smoke_records()[0][0], BoundaryTokenizer(), max_length=16
        )

        self.assertEqual(encoded["input_ids"], [10, 11, 12, 3])
        self.assertEqual(encoded["labels"], [-100, -100, 12, 3])

    def test_missing_assistant_eos_is_rejected(self):
        api = self.api()

        class MissingEosTokenizer:
            eos_token_id = 3
            pad_token_id = 0

            def apply_chat_template(self, messages, tokenize, add_generation_prompt):
                return [10, 11] if add_generation_prompt else [10, 11, 12]

        with self.assertRaisesRegex(api.TrainingDataError, "assistant EOS"):
            api.tokenize_training_record(
                generate_smoke_records()[0][0], MissingEosTokenizer(), max_length=16
            )

    def test_non_whitespace_suffix_after_assistant_eos_is_rejected(self):
        api = self.api()

        class UnexpectedSuffixTokenizer:
            eos_token_id = 3
            pad_token_id = 0

            def apply_chat_template(self, messages, tokenize, add_generation_prompt):
                return [10, 11] if add_generation_prompt else [10, 11, 12, 3, 14]

            def decode(self, token_ids, skip_special_tokens=False):
                return "not-whitespace"

        with self.assertRaisesRegex(api.TrainingDataError, "unexpected tokens"):
            api.tokenize_training_record(
                generate_smoke_records()[0][0],
                UnexpectedSuffixTokenizer(),
                max_length=16,
            )

    def test_collator_right_pads_ids_masks_and_labels(self):
        api = self.api()
        tokenizer = FakeTokenizer()
        collator = api.CausalJsonCollator(tokenizer, tensor_factory=lambda values: values)

        batch = collator(
            [
                {"input_ids": [11, 12, 3], "attention_mask": [1, 1, 1], "labels": [-100, 12, 3]},
                {"input_ids": [21, 3], "attention_mask": [1, 1], "labels": [-100, 3]},
            ]
        )

        self.assertEqual(batch["input_ids"], [[11, 12, 3], [21, 3, 0]])
        self.assertEqual(batch["attention_mask"], [[1, 1, 1], [1, 1, 0]])
        self.assertEqual(batch["labels"], [[-100, 12, 3], [-100, 3, -100]])


if __name__ == "__main__":
    unittest.main()
