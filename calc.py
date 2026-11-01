#!/usr/bin/env python3
"""Evaluate arithmetic expressions safely, for checking a report's math.

Only numbers, + - * / // % **, parentheses and round/abs/min/max are allowed:
no names, attribute access, imports or function calls beyond those.
Usage: calc.py "10000 * 1.1542 ** 10" ["(1.3017 ** 10 - 1) * 100" ...]
"""
import ast
import math
import operator
import sys

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
       ast.USub: operator.neg, ast.UAdd: operator.pos}
FUNCS = {"round": round, "abs": abs, "min": min, "max": max}
LIMIT = 1e100  # far beyond any money figure; stops expressions that would exhaust memory or CPU


def checked(value):
    if abs(value) > LIMIT:
        raise ValueError("result too large")
    return value


def evaluate(node):
    if isinstance(node, ast.Expression):
        return evaluate(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return checked(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        left, right = evaluate(node.left), evaluate(node.right)
        if isinstance(node.op, ast.Pow) and left not in (0, 1, -1) and abs(right) * math.log10(abs(left)) > 100:
            raise ValueError("result too large")  # checked before computing, not after
        return checked(OPS[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return checked(OPS[type(node.op)](evaluate(node.operand)))
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS
            and not node.keywords):
        return checked(FUNCS[node.func.id](*[evaluate(a) for a in node.args]))
    raise ValueError(f"not allowed: {ast.dump(node)[:60]}")


def main():
    for expr in sys.argv[1:]:
        try:
            print(f"{expr} = {evaluate(ast.parse(expr, mode='eval'))}")
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as e:
            print(f"{expr} -> error: {e}")


if __name__ == "__main__":
    main()
