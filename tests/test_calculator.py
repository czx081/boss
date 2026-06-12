import unittest

from app.tools.calculator import calculate


class CalculatorTests(unittest.TestCase):
    def test_calculator_evaluates_arithmetic(self):
        self.assertEqual(calculate("(18 + 6) * 4")["result"], 96)

    def test_calculator_rejects_non_arithmetic(self):
        expressions = [
            "__import__('os').system('echo unsafe')",
            "[1, 2, 3][0]",
            "open('secret.txt')",
        ]
        for expression in expressions:
            with self.subTest(expression=expression):
                with self.assertRaises(ValueError):
                    calculate(expression)

    def test_calculator_rejects_large_exponent(self):
        with self.assertRaises(ValueError):
            calculate("2 ** 101")


if __name__ == "__main__":
    unittest.main()
