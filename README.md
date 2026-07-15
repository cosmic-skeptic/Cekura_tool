# Cekura Evaluator Builder

A self-contained Streamlit tool that turns a **bot configuration** into a set of
**ready-to-paste Cekura evaluators**. No API calls, no database — the evaluator
library and personalities are bundled as local JSON, and all generation logic
lives in `logic.py`.

## What it does

1. You configure a bot in the sidebar (stage, goal, company, channels, PTP
   window, languages, collateral, helpline, etc.).
2. The engine:
   - **filters** the library by each card's *applicability expression*
     (e.g. a pay-now card only appears for a pay-now bot),
   - **picks the right fork** (PTP-date vs pay-now; chronic vs non-chronic),
   - **computes derived values** (e.g. `PTP_WINDOW_PLUS = window + buffer`, the
     "too-far, should-be-pushed" date — so one card works whether the window is
     2 days or 40),
   - **resolves conditional blocks** (`[[IF HAS_BRANCH]] … [[ENDIF]]`),
   - **substitutes tokens** (`{{COMPANY}}`, `{{TOLL_FREE}}`, …).
3. You get finished evaluator cards (Instruction + Expected Outcome + the
   Personality to select), copyable, plus **Download all** as Markdown or JSON.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the URL Streamlit prints (usually http://localhost:8501).

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI |
| `logic.py` | Generation engine (applicability, derived values, conditionals, token substitution, exports) |
| `evaluator_library.json` | The universal evaluator library (the source of truth) |
| `personalities.json` | Reusable Cekura test-agent personalities |
| `requirements.txt` | Just Streamlit |

## Extending the library

Everything is data-driven — **you don't touch `app.py` to add evaluators.**
Add an object to `evaluator_library.json → evaluators`:

```json
{
  "id": "NEW-01",
  "category": "Payment",
  "priority": "P0",
  "scenario": "Short human-readable title",
  "applicability": "stage=='PostDue' and goal in ('PTP-date','Pay-now')",
  "tokens": ["COMPANY", "TOLL_FREE"],
  "personality": "Reluctant Negotiator",
  "instruction": "SPINE ... CURVEBALLS ...  with {{TOKENS}} and [[IF HAS_APP]]...[[ENDIF]]",
  "expected": "CHECKPOINTS ...  NEVER ..."
}
```

### Applicability expressions
Written against the resolved context; evaluated by a **safe** mini-evaluator
(no arbitrary code). Supported: names, string/number/tuple literals, `==`,
`!=`, `in`, `not in`, `and`, `or`, `not`, `True/False`.

Useful names available in an expression:
`stage`, `goal`, `delinquency`, `collateral`, and the boolean flags
`IS_PAY_NOW`, `IS_PTP_DATE`, `IS_BILINGUAL`, `HAS_BRANCH`, `HAS_APP`,
`HAS_CASH`, `HAS_LINK`, `HAS_HELPLINE`, `IS_VEHICLE`, `IS_SECURED`.

If an expression fails to parse, the card is **excluded** (fail-safe), so a
typo never silently ships a wrong test.

### Conditional text blocks
`[[IF FLAG]] text [[ENDIF]]` and `[[IF NOT FLAG]] text [[ENDIF]]`, where `FLAG`
is any boolean above. Used to include/exclude a line (e.g. a branch line only
when the bot has a branch channel).

### Tokens
`{{TOKEN}}` is replaced from the resolved context. Base tokens come from config;
derived ones are computed in `logic.compute_derived`. If a token can't be
resolved it's left visible in the output and flagged in the UI so you notice.

### Derived values (where the "params" magic lives)
See `logic.compute_derived`. The PTP window is the key example:

- `PTP_WINDOW` = the configured number
- `PTP_WINDOW_NEAR` = a within-window date (or `today` if window is 0)
- `PTP_WINDOW_PLUS` = `window + max(round(window*0.5), 3)` — a date comfortably
  beyond the window, used as the "too far, must be pushed/rejected" offer

Because the instruction text references these tokens rather than hard numbers,
the *same* card produces a correct test for a 2-day bot and a 40-day bot.

## How each evaluator is written

- **Fresh call** from connect (no mid-call entry; the customer *name* is set by
  the Cekura Personality, not in the instruction).
- **Instruction = SPINE + CURVEBALLS**: a scripted arc plus a bank of
  loophole / social-engineering / backtracking moves the test agent throws.
  The test agent behaves like a real, messy, adversarial customer.
- **Expected Outcome = CHECKPOINTS + NEVER**: checkpoint-by-checkpoint
  assertions plus explicit hard-fail conditions, so a pass genuinely means the
  scenario holds without loopholes.
- **Relative timing only** — no absolute dates; windows are relative to config.

## Notes / roadmap

- A few cards describe two variants inline ("run variant A or B" — death,
  bounce-vs-offer). A future version can split these into two generated cards
  automatically; today they're one card the tester runs both ways.
- The `PTP_WINDOW_PLUS` buffer is a sensible default; tune it in
  `logic.compute_derived` once you see real bot windows.
- To wire this to Cekura directly later, replace the download step with an API
  push — the generation engine already produces exactly the fields Cekura needs.
