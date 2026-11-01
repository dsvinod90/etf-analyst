"""A calculator that evaluates plain arithmetic only, for checking a report's math safely.

Only numbers, + - * / // % **, parentheses and round/abs/min/max are allowed:
no names, attribute access, imports or function calls beyond those.

Usage:
    etf-calc "10000 * 1.1542 ** 10" ["(1.3017 ** 10 - 1) * 100" ...]
"""

import ast
import math
import operator
import sys
from collections.abc import Callable, Sequence

Number = int | float
BIN_OPS: dict[type[ast.operator], Callable[[Number, Number], Number]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
UNARY_OPS: dict[type[ast.unaryop], Callable[[Number], Number]] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
FUNCS: dict[str, Callable[..., Number]] = {"round": round, "abs": abs, "min": min, "max": max}
LIMIT = 1e100  # far beyond any money figure; stops expressions that would exhaust memory or CPU
MAX_POWER_DIGITS = 100  # refuse a ** b when the result would have more digits than this


def checked(value: Number) -> Number:
    """Return ``value`` unchanged, or raise ValueError if its magnitude exceeds LIMIT."""
    if abs(value) > LIMIT:
        raise ValueError("result too large")
    return value


def evaluate(node: ast.AST) -> Number:
    """Compute the value of a parsed arithmetic expression, allowing only plain math.

    Why: the verifier agent checks a report's arithmetic (e.g. "$10,000 grew to $42,000"), and
    the numbers come from a report written by an agent that reads web pages. Running that text
    with eval() or ``python3 -c`` would let injected text run any code, so the expression is
    parsed into a syntax tree (``ast.parse``) and only these node types are computed:

    - ``Expression``: the wrapper ``ast.parse(..., mode="eval")`` returns; evaluate its body.
    - ``Constant``: an int or float literal, e.g. ``1.1542``.
    - ``BinOp``: ``+ - * / // % **`` between two sub-expressions, evaluated recursively.
    - ``UnaryOp``: a leading ``-`` or ``+``, e.g. ``-5``.
    - ``Call``: ``round()``, ``abs()``, ``min()`` or ``max()`` by name, positional args only.

    Anything else is refused: names (``x``), attributes (``(1).__class__``), other calls
    (``open``, ``__import__``), strings, lists, lambdas. Every literal and intermediate result
    is capped at LIMIT, powers are size-checked *before* they're computed, and ``round()``
    digits must be 0-10, so no expression can tie up CPU or memory.

    For ``2 + 3 * 4`` the tree is ``BinOp(2, Add, BinOp(3, Mult, 4))``: the inner BinOp gives
    12, then the outer one gives 14.

    Examples (via ``main()``)::

        10000 * 1.1542 ** 10                -> 41957.60...  ($10,000 at 15.42%/yr for 10 years)
        round((1.3017 ** 10 - 1) * 100, 1)  -> 1296.7       (10-year total gain in %)
        __import__('os').system('rm -rf ~') -> error: not allowed: Call(...)
        x + 1                               -> error: not allowed: Name(...)
        10 ** 101                           -> error: result too large
        round(1, -1000000000)               -> error: round() digits must be ... from 0 to 10

    Args:
        node: A node from ``ast.parse(text, mode="eval")``.

    Returns:
        The numeric result.

    Raises:
        ValueError: The expression uses anything outside the allowlist, or is too large.
        ZeroDivisionError: The expression divides by zero.
    """
    if isinstance(node, ast.Expression):
        return evaluate(node.body)
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int | float)
        and not isinstance(node.value, bool)  # True/False are ints in Python; not numbers here
    ):
        return checked(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in BIN_OPS:
        left, right = evaluate(node.left), evaluate(node.right)
        if (
            isinstance(node.op, ast.Pow)
            and left not in (0, 1, -1)
            and abs(right) * math.log10(abs(left)) > MAX_POWER_DIGITS
        ):
            raise ValueError("result too large")  # checked before computing, not after
        return checked(BIN_OPS[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPS:
        return checked(UNARY_OPS[type(node.op)](evaluate(node.operand)))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in FUNCS
        and not node.keywords
    ):
        args = [evaluate(a) for a in node.args]
        # round(x, -10**9) makes CPython build a billion-digit integer, so bound the digits
        if node.func.id == "round" and len(args) == 2 and not _valid_round_digits(args[1]):
            raise ValueError("round() digits must be a whole number from 0 to 10")
        return checked(FUNCS[node.func.id](*args))
    raise ValueError(f"not allowed: {ast.dump(node)[:60]}")


def _valid_round_digits(digits: Number) -> bool:
    return isinstance(digits, int) and 0 <= digits <= 10


def main(argv: Sequence[str] | None = None) -> None:
    """Evaluate each expression given on the command line and print the result or the error."""
    for expr in sys.argv[1:] if argv is None else argv:
        try:
            print(f"{expr} = {evaluate(ast.parse(expr, mode='eval'))}")
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as e:
            print(f"{expr} -> error: {e}")


if __name__ == "__main__":
    main()
