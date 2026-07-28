from __future__ import annotations

import unittest

from god_bot.lisp import LispError, evaluate_lisp


class LispEvaluatorTests(unittest.TestCase):
    def test_evaluates_nested_arithmetic(self) -> None:
        self.assertEqual(evaluate_lisp("(+ 1 (* 2 3))"), "7")
        self.assertEqual(evaluate_lisp("(/ 8 2)"), "4")
        self.assertEqual(evaluate_lisp("(expt 2 8)"), "256")

    def test_supports_if_and_let(self) -> None:
        self.assertEqual(evaluate_lisp("(if (> 3 2) 10 20)"), "10")
        self.assertEqual(
            evaluate_lisp("(let ((x 2) (y 3)) (+ x y))"),
            "5",
        )

    def test_supports_cond(self) -> None:
        expression = (
            "(let ((x 5)) "
            "(cond ((< x 0) -1) ((= x 0) 0) (else 1)))"
        )
        self.assertEqual(evaluate_lisp(expression), "1")

    def test_supports_cons_car_cdr_and_null(self) -> None:
        self.assertEqual(evaluate_lisp("(cons 1 '(2 3))"), "(1 2 3)")
        self.assertEqual(evaluate_lisp("(car '(a b c))"), "a")
        self.assertEqual(evaluate_lisp("(cdr '(a b c))"), "(b c)")
        self.assertEqual(evaluate_lisp("(null '())"), "#t")
        self.assertEqual(evaluate_lisp("(null? '(1))"), "#f")

    def test_supports_strings_and_lists(self) -> None:
        self.assertEqual(evaluate_lisp('(length "神様")'), "2")
        self.assertEqual(evaluate_lisp("(length (list 1 2 3))"), "3")

    def test_rejects_unsafe_or_invalid_operations(self) -> None:
        with self.assertRaises(LispError):
            evaluate_lisp("(open-file \"/etc/passwd\")")
        with self.assertRaises(LispError):
            evaluate_lisp("(/ 1 0)")
        with self.assertRaises(LispError):
            evaluate_lisp("(expt 2 1000)")
        with self.assertRaises(LispError):
            evaluate_lisp("(+ 1 2")


if __name__ == "__main__":
    unittest.main()
