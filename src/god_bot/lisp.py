from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import reduce
from typing import TypeAlias


class LispError(ValueError):
    pass


class Symbol(str):
    pass


Expression: TypeAlias = int | float | bool | str | Symbol | list["Expression"]
Value: TypeAlias = int | float | bool | str | Symbol | list["Value"]


@dataclass(slots=True)
class _ParseState:
    tokens: list[str]
    position: int = 0
    nodes: int = 0


def _tokenize(source: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if char in "()'":
            tokens.append(char)
            index += 1
            continue
        if char == '"':
            start = index
            index += 1
            escaped = False
            while index < len(source):
                current = source[index]
                index += 1
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    break
            else:
                raise LispError("文字列の `\"` が閉じていないよ")
            tokens.append(source[start:index])
            continue
        start = index
        while (
            index < len(source)
            and not source[index].isspace()
            and source[index] not in "()'\""
        ):
            index += 1
        tokens.append(source[start:index])
    return tokens


def _atom(token: str) -> Expression:
    if token == "#t":
        return True
    if token == "#f":
        return False
    if token.startswith('"'):
        try:
            value = json.loads(token)
        except json.JSONDecodeError as error:
            raise LispError("文字列を読み取れなかったよ") from error
        return str(value)
    try:
        return int(token)
    except ValueError:
        try:
            value = float(token)
        except ValueError:
            return Symbol(token)
        if not math.isfinite(value):
            raise LispError("有限の数値だけ使ってね")
        return value


def _parse_one(state: _ParseState, *, depth: int = 0) -> Expression:
    if depth > 24:
        raise LispError("S式の入れ子が深すぎるよ")
    if state.position >= len(state.tokens):
        raise LispError("S式が途中で終わっているよ")
    state.nodes += 1
    if state.nodes > 256:
        raise LispError("S式が大きすぎるよ")
    token = state.tokens[state.position]
    state.position += 1
    if token == "(":
        values: list[Expression] = []
        while True:
            if state.position >= len(state.tokens):
                raise LispError("`)` が足りないよ")
            if state.tokens[state.position] == ")":
                state.position += 1
                return values
            values.append(_parse_one(state, depth=depth + 1))
    if token == ")":
        raise LispError("`)` が多すぎるよ")
    if token == "'":
        return [Symbol("quote"), _parse_one(state, depth=depth + 1)]
    return _atom(token)


def parse_lisp(source: str) -> Expression:
    tokens = _tokenize(source)
    if not tokens:
        raise LispError("例: `lisp (+ 1 (* 2 3))`")
    state = _ParseState(tokens)
    expression = _parse_one(state)
    if state.position != len(tokens):
        raise LispError("S式は一度に1つだけ指定してね")
    return expression


def _numbers(values: list[Value]) -> list[int | float]:
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise LispError("この演算には数値を指定してね")
    return [value for value in values if isinstance(value, (int, float))]


def _arithmetic(operator: str, values: list[Value]) -> Value:
    numbers = _numbers(values)
    if operator == "+":
        result: int | float = sum(numbers)
    elif operator == "*":
        result = math.prod(numbers)
    elif operator == "-":
        if not numbers:
            raise LispError("`-` には1つ以上の数値が必要だよ")
        result = -numbers[0] if len(numbers) == 1 else reduce(
            lambda left, right: left - right,
            numbers[1:],
            numbers[0],
        )
    elif operator == "/":
        if not numbers:
            raise LispError("`/` には1つ以上の数値が必要だよ")
        divisors = numbers if len(numbers) > 1 else [1, numbers[0]]
        try:
            result = reduce(
                lambda left, right: left / right,
                divisors[1:],
                divisors[0],
            )
        except ZeroDivisionError as error:
            raise LispError("0では割れないよ") from error
    elif operator in {"mod", "remainder"}:
        if len(numbers) != 2:
            raise LispError(f"`{operator}` には数値が2つ必要だよ")
        try:
            result = numbers[0] % numbers[1]
        except ZeroDivisionError as error:
            raise LispError("0では割れないよ") from error
    elif operator == "expt":
        if len(numbers) != 2:
            raise LispError("`expt` には数値が2つ必要だよ")
        if abs(numbers[1]) > 100:
            raise LispError("指数が大きすぎるよ")
        result = numbers[0] ** numbers[1]
    else:
        raise LispError(f"未知の演算だよ: {operator}")
    if isinstance(result, complex) or not math.isfinite(float(result)):
        raise LispError("計算結果を扱えないよ")
    if abs(result) > 1e100:
        raise LispError("計算結果が大きすぎるよ")
    return result


def _compare(operator: str, values: list[Value]) -> bool:
    if len(values) < 2:
        raise LispError(f"`{operator}` には2つ以上の値が必要だよ")
    pairs = zip(values, values[1:])
    try:
        if operator == "=":
            return all(left == right for left, right in pairs)
        numbers = _numbers(values)
        number_pairs = zip(numbers, numbers[1:])
        if operator == "<":
            return all(left < right for left, right in number_pairs)
        if operator == "<=":
            return all(left <= right for left, right in number_pairs)
        if operator == ">":
            return all(left > right for left, right in number_pairs)
        if operator == ">=":
            return all(left >= right for left, right in number_pairs)
    except TypeError as error:
        raise LispError("比較できない値だよ") from error
    raise LispError(f"未知の比較だよ: {operator}")


def _evaluate(
    expression: Expression,
    environment: dict[str, Value],
    *,
    depth: int = 0,
) -> Value:
    if depth > 32:
        raise LispError("評価の入れ子が深すぎるよ")
    if isinstance(expression, Symbol):
        if expression in environment:
            return environment[expression]
        raise LispError(f"未定義の名前だよ: {expression}")
    if not isinstance(expression, list):
        return expression
    if not expression:
        return []
    operator = expression[0]
    if not isinstance(operator, Symbol):
        raise LispError("リストの先頭には演算名が必要だよ")
    arguments = expression[1:]

    if operator == "quote":
        if len(arguments) != 1:
            raise LispError("`quote` には値が1つ必要だよ")
        return arguments[0]
    if operator == "if":
        if len(arguments) != 3:
            raise LispError("`if` は条件・真・偽の3つを指定してね")
        condition = _evaluate(arguments[0], environment, depth=depth + 1)
        branch = arguments[1] if condition is not False else arguments[2]
        return _evaluate(branch, environment, depth=depth + 1)
    if operator == "cond":
        for clause in arguments:
            if not isinstance(clause, list) or len(clause) < 2:
                raise LispError(
                    "`cond` の各節は `(条件 結果...)` で書いてね"
                )
            condition_expression = clause[0]
            matched = (
                isinstance(condition_expression, Symbol)
                and condition_expression == "else"
            )
            if not matched:
                matched = (
                    _evaluate(
                        condition_expression,
                        environment,
                        depth=depth + 1,
                    )
                    is not False
                )
            if matched:
                result: Value = False
                for body in clause[1:]:
                    result = _evaluate(
                        body,
                        environment,
                        depth=depth + 1,
                    )
                return result
        return False
    if operator in {"and", "or"}:
        result: Value = True if operator == "and" else False
        for argument in arguments:
            result = _evaluate(argument, environment, depth=depth + 1)
            if operator == "and" and result is False:
                return False
            if operator == "or" and result is not False:
                return result
        return result
    if operator == "let":
        if len(arguments) < 2 or not isinstance(arguments[0], list):
            raise LispError("例: `(let ((x 2)) (+ x 3))`")
        local = dict(environment)
        for binding in arguments[0]:
            if (
                not isinstance(binding, list)
                or len(binding) != 2
                or not isinstance(binding[0], Symbol)
            ):
                raise LispError("letの束縛は `(名前 値)` で書いてね")
            local[str(binding[0])] = _evaluate(
                binding[1], environment, depth=depth + 1
            )
        result: Value = False
        for body in arguments[1:]:
            result = _evaluate(body, local, depth=depth + 1)
        return result

    values = [
        _evaluate(argument, environment, depth=depth + 1)
        for argument in arguments
    ]
    if operator in {"+", "-", "*", "/", "mod", "remainder", "expt"}:
        return _arithmetic(operator, values)
    if operator in {"=", "<", "<=", ">", ">="}:
        return _compare(operator, values)
    if operator == "not":
        if len(values) != 1:
            raise LispError("`not` には値が1つ必要だよ")
        return values[0] is False
    if operator == "list":
        return values
    if operator == "length":
        if len(values) != 1 or not isinstance(values[0], (list, str)):
            raise LispError("`length` にはリストか文字列が必要だよ")
        return len(values[0])
    if operator == "car":
        if len(values) != 1 or not isinstance(values[0], list) or not values[0]:
            raise LispError("`car` には空でないリストが必要だよ")
        return values[0][0]
    if operator == "cdr":
        if len(values) != 1 or not isinstance(values[0], list):
            raise LispError("`cdr` にはリストが必要だよ")
        return values[0][1:]
    if operator in {"null", "null?"}:
        if len(values) != 1:
            raise LispError(f"`{operator}` には値が1つ必要だよ")
        return isinstance(values[0], list) and not values[0]
    if operator == "cons":
        if len(values) != 2 or not isinstance(values[1], list):
            raise LispError("`cons` の2番目にはリストが必要だよ")
        return [values[0], *values[1]]
    if operator in {"min", "max"}:
        numbers = _numbers(values)
        if not numbers:
            raise LispError(f"`{operator}` には数値が必要だよ")
        return min(numbers) if operator == "min" else max(numbers)
    if operator == "abs":
        numbers = _numbers(values)
        if len(numbers) != 1:
            raise LispError("`abs` には数値が1つ必要だよ")
        return abs(numbers[0])
    raise LispError(f"許可されていない演算だよ: {operator}")


def _format_value(value: Value) -> str:
    if value is True:
        return "#t"
    if value is False:
        return "#f"
    if isinstance(value, list):
        return "(" + " ".join(_format_value(item) for item in value) + ")"
    if isinstance(value, Symbol):
        return value
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, ".12g")
    return str(value)


def evaluate_lisp(source: str) -> str:
    if len(source) > 1_000:
        raise LispError("S式は1,000文字以内にしてね")
    expression = parse_lisp(source)
    result = _evaluate(
        expression,
        {
            "pi": math.pi,
            "e": math.e,
        },
    )
    formatted = _format_value(result)
    if len(formatted) > 1_500:
        raise LispError("結果が長すぎるよ")
    return formatted
