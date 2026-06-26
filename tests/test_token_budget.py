import unittest

from app.agent.token_budget import (
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tokens,
    trim_messages_to_budget,
)


class TokenBudgetTests(unittest.TestCase):
    def test_estimate_tokens_is_stable_and_non_zero_for_text(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("abcd"), 1)
        self.assertEqual(estimate_tokens("abcde"), 2)

    def test_estimate_message_tokens_counts_role_and_content(self):
        message = {"role": "user", "content": "abcdefgh"}

        self.assertEqual(estimate_message_tokens(message), 3)

    def test_estimate_messages_tokens_sums_all_messages(self):
        messages = [
            {"role": "user", "content": "abcd"},
            {"role": "assistant", "content": "abcd"},
        ]

        self.assertEqual(
            estimate_messages_tokens(messages),
            estimate_message_tokens(messages[0]) + estimate_message_tokens(messages[1]),
        )

    def test_trim_messages_to_budget_keeps_recent_messages(self):
        messages = [
            {"role": "user", "content": "old message " * 20},
            {"role": "assistant", "content": "middle message"},
            {"role": "user", "content": "latest"},
        ]

        trimmed = trim_messages_to_budget(messages, max_tokens=10)

        self.assertEqual(trimmed[-1]["content"], "latest")
        self.assertNotEqual(trimmed[0]["content"], messages[0]["content"])

    def test_trim_messages_to_budget_truncates_single_oversized_recent_message(self):
        messages = [{"role": "user", "content": "x" * 200}]

        trimmed = trim_messages_to_budget(messages, max_tokens=10)

        self.assertEqual(len(trimmed), 1)
        self.assertLessEqual(estimate_message_tokens(trimmed[0]), 10)
        self.assertTrue(trimmed[0]["content"])

    def test_trim_messages_to_budget_returns_empty_for_zero_budget(self):
        messages = [{"role": "user", "content": "hello"}]

        self.assertEqual(trim_messages_to_budget(messages, max_tokens=0), [])


if __name__ == "__main__":
    unittest.main()

