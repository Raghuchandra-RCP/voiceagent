"""
math_eval tool
--------------
Safe arithmetic evaluator. Handles:
  - basic arithmetic  (+, -, *, /, //, %, **)
  - unary minus
  - parentheses
  - percentages  ("15% of 240" → 36)
  - math functions   (sqrt, sin, cos, tan, log, log2, log10, exp, ...)
  - math constants   (pi, e, tau)

Uses a small ast.NodeVisitor whitelist so it CANNOT execute arbitrary
code (no imports, no attribute access, no function definitions).
"""

from __future__ import annotations

import ast
import json
import math
import operator
import re
from typing import Any

from app.tools.base import Tool

# Allowed AST node → binary op
_BIN_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Whitelisted names — math constants + a curated set of math functions
_NAMES: dict[str, Any] = {
    "pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf,
}
_FUNCS: dict[str, Any] = {
    name: getattr(math, name)
    for name in (
        "sqrt", "cbrt",
        "sin", "cos", "tan",
        "asin", "acos", "atan", "atan2",
        "sinh", "cosh", "tanh",
        "log", "log2", "log10", "exp",
        "ceil", "floor", "trunc",
        "degrees", "radians",
        "fabs", "factorial", "gcd",
        "pow", "hypot",
    )
    if hasattr(math, name)
}
_FUNCS["abs"] = abs
_FUNCS["round"] = round
_FUNCS["min"] = min
_FUNCS["max"] = max


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"only numeric constants allowed, got {type(node.value).__name__}")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"operator {type(node.op).__name__} not allowed")
        return op(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"unary op {type(node.op).__name__} not allowed")
        return op(_eval_node(node.operand))
    if isinstance(node, ast.Name):
        if node.id in _NAMES:
            return _NAMES[node.id]
        raise ValueError(f"name {node.id!r} not allowed")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("only bare function calls allowed")
        fn = _FUNCS.get(node.func.id)
        if fn is None:
            raise ValueError(f"function {node.func.id!r} not allowed")
        if node.keywords:
            raise ValueError("keyword args not allowed")
        return fn(*[_eval_node(a) for a in node.args])
    raise ValueError(f"AST node {type(node).__name__} not allowed")


# "15% of 240", "20 % of 80" → "15/100*240"
_PCT_OF = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


def _normalise(expr: str) -> str:
    e = expr.strip()
    # "15% of 240" → "(15/100)*240"
    e = _PCT_OF.sub(r"((\1)/100)*(\2)", e)
    # bare trailing "%" → "/100"
    e = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"((\1)/100)", e)
    # common english → symbols
    e = re.sub(r"\bplus\b", "+", e, flags=re.IGNORECASE)
    e = re.sub(r"\bminus\b", "-", e, flags=re.IGNORECASE)
    e = re.sub(r"\btimes\b", "*", e, flags=re.IGNORECASE)
    e = re.sub(r"\b(?:divided by|over)\b", "/", e, flags=re.IGNORECASE)
    e = re.sub(r"\bmod(?:ulo)?\b", "%", e, flags=re.IGNORECASE)
    e = re.sub(r"\bto the power of\b", "**", e, flags=re.IGNORECASE)
    e = re.sub(r"\bsquared\b", "**2", e, flags=re.IGNORECASE)
    e = re.sub(r"\bcubed\b", "**3", e, flags=re.IGNORECASE)
    e = re.sub(r"\bsquare root of\b", "sqrt", e, flags=re.IGNORECASE)
    return e


async def _handler(args: dict[str, Any]) -> str:
    expr = args.get("expression")
    if not isinstance(expr, str) or not expr.strip():
        return json.dumps({"error": "Missing 'expression'."})

    try:
        normalised = _normalise(expr)
        tree = ast.parse(normalised, mode="eval")
        value = _eval_node(tree)
    except ZeroDivisionError:
        return json.dumps({"error": "Division by zero."})
    except (ValueError, SyntaxError, TypeError) as exc:
        return json.dumps({"error": f"Cannot evaluate: {exc}"})
    except Exception as exc:  # noqa: BLE001 — surface anything weird
        return json.dumps({"error": f"math_eval failed: {type(exc).__name__}: {exc}"})

    # Prefer int display when result is whole
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return json.dumps({"expression": expr, "result": value})


TOOL = Tool(
    name="math_eval",
    description=(
        "Evaluate a math expression safely. Handles arithmetic (+ - * / // % **), "
        "parentheses, percentages ('15% of 240'), and common functions (sqrt, "
        "sin, cos, log, log2, log10, exp, abs, round, min, max, factorial). "
        "Constants pi, e, tau. Also understands words: 'plus', 'minus', "
        "'times', 'divided by', 'squared', 'square root of', 'to the power of'. "
        "Prefer this over asking the LLM to do arithmetic in its head."
    ),
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": (
                    "Math expression. Examples: '15% of 240', 'sqrt(1024)', "
                    "'(3 + 4) * 2', 'log2(65536)', 'sin(pi/2)', "
                    "'20 divided by 4 squared'."
                ),
            },
        },
        "required": ["expression"],
    },
    handler=_handler,
    preamble="",
    response_mode="full",
    tags=("compute",),
)
