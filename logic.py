"""
logic.py — the generation engine for the Cekura Evaluator Builder.

No network, no database. Pure functions over the bundled JSON library + a
config dict the UI collects. Responsibilities:

  1. compute_derived(config)      -> dict of derived values & boolean flags
  2. is_applicable(expr, ctx)     -> safe evaluation of an applicability string
  3. resolve_conditionals(text,ctx) -> strip/keep [[IF ...]]...[[ENDIF]] blocks
  4. substitute_tokens(text, ctx) -> replace {{TOKEN}} with resolved values
  5. build_evaluators(config, lib)-> list of finished, ready-to-paste cards

The applicability / conditional expressions are evaluated with a *restricted*
AST evaluator (safe_eval) so we never run arbitrary code from the JSON.
"""

import ast
import json
import operator
import re
from pathlib import Path

HERE = Path(__file__).parent


# --------------------------------------------------------------------------
# Loading bundled data
# --------------------------------------------------------------------------
def load_library(path: str | Path | None = None) -> dict:
    path = Path(path) if path else HERE / "evaluator_library.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_personalities(path: str | Path | None = None) -> dict:
    path = Path(path) if path else HERE / "personalities.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# Number-to-words (small, for PTP window wording; Indian-style not needed here)
# --------------------------------------------------------------------------
_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
         "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]


def num_to_words(n: int) -> str:
    if n < 0:
        return "minus " + num_to_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] + ("-" + _ONES[o] if o else "")
    if n < 1000:
        h, rest = divmod(n, 100)
        return _ONES[h] + " hundred" + (" " + num_to_words(rest) if rest else "")
    return str(n)  # windows won't realistically exceed this


# --------------------------------------------------------------------------
# Derived values
# --------------------------------------------------------------------------
def compute_derived(config: dict) -> dict:
    """
    Take the raw config the UI collected and produce a full context dict of
    both base values (as strings for substitution) and derived booleans/values.
    """
    ctx: dict = {}

    # ---- base passthroughs (strings for substitution) ----
    ctx["STAGE"] = config.get("stage", "")
    ctx["GOAL"] = config.get("goal", "")
    ctx["COMPANY"] = config.get("company_name", "").strip() or "the company"
    ctx["PERSONA"] = config.get("persona", "").strip() or "the agent"
    ctx["TOLL_FREE"] = config.get("toll_free", "").strip() or "the customer support number"
    ctx["APP_NAME"] = config.get("app_name", "").strip() or "the app"
    ctx["BRANCH_HOURS"] = config.get("branch_hours", "").strip() or "branch hours"
    ctx["LANG1"] = config.get("lang_primary", "").strip() or "the primary language"
    ctx["LANG2"] = config.get("lang_secondary", "").strip()
    ctx["HELPLINE"] = config.get("helpline", "").strip()

    channels = config.get("payment_channels", []) or []
    ctx["_channels_list"] = channels
    ctx["CHANNELS"] = _format_channels(channels, ctx["APP_NAME"])

    # ---- PTP window logic (the important one) ----
    window = config.get("ptp_window_days", None)
    try:
        window = int(window) if window is not None and window != "" else None
    except (TypeError, ValueError):
        window = None

    if window is not None:
        ctx["_ptp_window_int"] = window
        ctx["PTP_WINDOW"] = str(window)
        ctx["PTP_WINDOW_WORDS"] = num_to_words(window) if window > 0 else "zero"
        # near = within window (or 'today' if window == 0)
        ctx["PTP_WINDOW_NEAR"] = "today" if window == 0 else str(window)
        # plus = comfortably beyond the window -> the "too far, must be pushed" offer
        buffer = max(round(window * 0.5), 3)
        ctx["PTP_WINDOW_PLUS"] = str(window + buffer)
    else:
        ctx["_ptp_window_int"] = None
        ctx["PTP_WINDOW"] = "the acceptable window"
        ctx["PTP_WINDOW_WORDS"] = "the acceptable number of"
        ctx["PTP_WINDOW_NEAR"] = "a near"
        ctx["PTP_WINDOW_PLUS"] = "a far"

    # ---- collateral ----
    collateral = config.get("collateral_type", "unsecured")
    ctx["_collateral"] = collateral

    # ---- delinquency ----
    ctx["_delinquency"] = config.get("delinquency", "1st-bounce")

    # ---- boolean flags used by applicability + conditional blocks ----
    ctx_flags = {
        "IS_PAY_NOW": ctx["GOAL"] == "Pay-now",
        "IS_PTP_DATE": ctx["GOAL"] == "PTP-date",
        "IS_BILINGUAL": bool(ctx["LANG2"]),
        "HAS_BRANCH": "branch" in channels,
        "HAS_APP": "app" in channels,
        "HAS_CASH": "cash" in channels,
        "HAS_LINK": "link" in channels,
        "HAS_HELPLINE": bool(ctx["HELPLINE"]),
        "IS_VEHICLE": collateral == "vehicle",
        "IS_SECURED": collateral in ("vehicle", "gold", "property"),
    }
    ctx.update(ctx_flags)

    # names used inside applicability expressions
    ctx["stage"] = ctx["STAGE"]
    ctx["goal"] = ctx["GOAL"]
    ctx["delinquency"] = ctx["_delinquency"]
    ctx["collateral"] = collateral

    return ctx


def _format_channels(channels: list, app_name: str) -> str:
    label_map = {
        "link": "the payment link",
        "app": f"the {app_name}",
        "branch": "the nearest branch",
        "cash": "cash at the branch",
    }
    labels = [label_map.get(c, c) for c in channels]
    if not labels:
        return "the available payment channels"
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " or " + labels[-1]


# --------------------------------------------------------------------------
# Safe expression evaluation (applicability + conditional flags)
# --------------------------------------------------------------------------
_ALLOWED_BINOPS = {ast.And: all, ast.Or: any}
_ALLOWED_CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


def safe_eval(expr: str, ctx: dict) -> bool:
    """
    Evaluate a restricted boolean expression against ctx.
    Supports: names, str/num/tuple literals, ==, !=, in, not in,
    and/or/not, True/False. Anything else raises.
    """
    expr = expr.strip()
    if expr in ("", "True", "true"):
        return True
    if expr in ("False", "false"):
        return False

    tree = ast.parse(expr, mode="eval")

    def _ev(node):
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.BoolOp):
            vals = [_ev(v) for v in node.values]
            return _ALLOWED_BINOPS[type(node.op)](vals)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not _ev(node.operand)
        if isinstance(node, ast.Compare):
            left = _ev(node.left)
            result = True
            for op, comp in zip(node.ops, node.comparators):
                right = _ev(comp)
                result = result and _ALLOWED_CMP[type(op)](left, right)
                left = right
            return result
        if isinstance(node, ast.Name):
            if node.id in ("True", "False"):
                return node.id == "True"
            return ctx.get(node.id, None)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Tuple):
            return tuple(_ev(e) for e in node.elts)
        if isinstance(node, ast.List):
            return [_ev(e) for e in node.elts]
        raise ValueError(f"Unsupported expression element: {ast.dump(node)}")

    return bool(_ev(tree))


def is_applicable(expr: str, ctx: dict) -> bool:
    try:
        return safe_eval(expr, ctx)
    except Exception:
        # Fail safe: if an expression can't be parsed, exclude the card
        # rather than silently including a possibly-wrong one.
        return False


# --------------------------------------------------------------------------
# Conditional block resolution  [[IF flag]] ... [[ENDIF]]  and [[IF NOT flag]]
# --------------------------------------------------------------------------
_COND_RE = re.compile(r"\[\[IF\s+(NOT\s+)?([A-Z_]+)\]\](.*?)\[\[ENDIF\]\]",
                      re.DOTALL)


def resolve_conditionals(text: str, ctx: dict) -> str:
    def _repl(m):
        negate = bool(m.group(1))
        flag = m.group(2)
        body = m.group(3)
        val = bool(ctx.get(flag, False))
        keep = (not val) if negate else val
        return body if keep else ""

    # loop until stable (handles no nesting; our data has no nesting)
    prev = None
    out = text
    while prev != out:
        prev = out
        out = _COND_RE.sub(_repl, out)
    # tidy any doubled blank lines left behind
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip("\n")


# --------------------------------------------------------------------------
# Token substitution  {{TOKEN}}
# --------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def substitute_tokens(text: str, ctx: dict) -> tuple[str, list]:
    """Return (substituted_text, list_of_unresolved_tokens)."""
    unresolved = []

    def _repl(m):
        key = m.group(1)
        if key in ctx and ctx[key] not in (None, ""):
            return str(ctx[key])
        unresolved.append(key)
        return m.group(0)  # leave the token visible so the user notices

    out = _TOKEN_RE.sub(_repl, text)
    return out, unresolved


# --------------------------------------------------------------------------
# Main build
# --------------------------------------------------------------------------
def build_evaluators(config: dict, library: dict | None = None,
                     personalities: dict | None = None) -> dict:
    """
    Returns:
      {
        "included": [ {id, category, priority, scenario, personality,
                       personality_settings, instruction, expected,
                       unresolved_tokens}, ... ],
        "excluded": [ {id, scenario, reason}, ... ],
        "context":  ctx  (for debugging / display)
      }
    """
    library = library or load_library()
    personalities = personalities or load_personalities()
    ctx = compute_derived(config)

    included, excluded = [], []

    for card in library["evaluators"]:
        appl = card.get("applicability", "True")
        if not is_applicable(appl, ctx):
            excluded.append({
                "id": card["id"],
                "scenario": card["scenario"],
                "reason": f"applicability not met: {appl}",
            })
            continue

        instr = resolve_conditionals(card["instruction"], ctx)
        expec = resolve_conditionals(card["expected"], ctx)
        instr, u1 = substitute_tokens(instr, ctx)
        expec, u2 = substitute_tokens(expec, ctx)
        unresolved = sorted(set(u1 + u2))

        pers_name = card.get("personality", "")
        pers = personalities.get(pers_name, {})

        included.append({
            "id": card["id"],
            "category": card["category"],
            "priority": card["priority"],
            "scenario": card["scenario"],
            "personality": pers_name,
            "personality_settings": pers,
            "instruction": instr,
            "expected": expec,
            "unresolved_tokens": unresolved,
        })

    # stable, useful ordering: P0 first, then by category
    prio_rank = {"P0": 0, "P1": 1, "P2": 2}
    included.sort(key=lambda c: (prio_rank.get(c["priority"], 9), c["category"], c["id"]))

    return {"included": included, "excluded": excluded, "context": ctx}


# --------------------------------------------------------------------------
# Export helpers
# --------------------------------------------------------------------------
def to_markdown(result: dict, config: dict) -> str:
    lines = []
    lines.append(f"# Cekura Evaluators — {config.get('company_name','')} "
                 f"({config.get('stage','')}/{config.get('goal','')})")
    lines.append("")
    for c in result["included"]:
        lines.append(f"## {c['id']} — {c['scenario']}  ({c['priority']})")
        lines.append(f"**Category:** {c['category']}  |  "
                     f"**Personality:** {c['personality']}")
        if c["unresolved_tokens"]:
            lines.append(f"> ⚠ Unresolved tokens: {', '.join(c['unresolved_tokens'])}")
        lines.append("")
        lines.append("**Instruction**")
        lines.append("```")
        lines.append(c["instruction"])
        lines.append("```")
        lines.append("**Expected Outcome**")
        lines.append("```")
        lines.append(c["expected"])
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def to_json_export(result: dict, config: dict) -> str:
    payload = {
        "config": config,
        "evaluators": [
            {k: c[k] for k in ("id", "category", "priority", "scenario",
                               "personality", "instruction", "expected",
                               "unresolved_tokens")}
            for c in result["included"]
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
