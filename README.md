# Cekura Evaluator Builder

A self-contained Streamlit tool that turns a **bot configuration** into a set of
**ready-to-paste Cekura evaluators**. No API calls, no database — the evaluator
library and personalities are bundled as local JSON, and all generation logic
lives in `logic.py`.

**Library v3.0 (deep): 60 standalone cards** across 15 categories (Identity,
Third-Party, PTP, Payment, Reminder, Rebuttal, Safety, Dispute, Escalation,
Compliance, Language, Persona, **Pronunciation**, Flow, Welcome), built against a
coverage audit of three production bots so each distinct scenario is regressed on
its own (no bundling).

### v3.0 deep format
Every card is rewritten so a *pass* means the scenario genuinely holds in the
real world, with no loopholes:

- **Instruction = a long branching spine (8–12 turns).** Each turn carries an
  explicit `IF the bot does X → you do Y` reaction, so the Cekura test agent
  adapts to the bot instead of reading a script. Inline **emotion + timing cues**
  (`(pause 3s)`, `(sound irritated)`, `(go silent ~8s)`) and a large
  **curveball bank** (8–10 loophole probes) per card. `[note: ...]` markers flag
  exactly what a failure looks like at each turn — the test agent reads these and
  plays adversarially toward the known weak spots.
- **Expected Outcome = exhaustive.** Per-turn **CHECKPOINTS** (one assertion per
  spine step: T1, T2, …), a **NEVER** list (hard fails), and an explicit
  **PASS BAR** describing a clean end-to-end run.
- **Dialogue** is natural spoken Indian mix — English + Hinglish + some Devanagari,
  real fillers and code-switching (not textbook Hindi). Borrower reasons are
  grounded across profiles (salaried, self-employed/traders, gig,
  semi-urban/rural/agri).

All cards run on a **fresh call** (from connect; no callee name — the Personality
supplies it) and use **relative** timing only, so one card works at any PTP window.

### Pronunciation cards (transcript + audio)
The `Pronunciation` category forces the bot to *say* the risky items (amounts,
dates, digits, times, brand/app names, credit-score-not-CIBIL, natural Hinglish).
The Expected Outcome checks the **transcript** (formatting/word-choice). For true
**acoustic** errors, attach Cekura's built-in **Pronunciation Check** / **Voice
Quality** metrics to the run — each such card notes this. A few proper-noun
checks (company/app name pronunciation) are flagged for manual audio review.

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

## Rebuilding the library

The library JSON is generated from a build script (source of truth):

```bash
python3 build_library_deep.py   # writes evaluator_library.json (v3.0 deep)
```

`build_library_deep.py` contains all 60 cards plus the grounding reason-bank
(authentic Indian BFSI borrower reasons). Edit cards there and re-run to
regenerate `evaluator_library.json`. The older `build_library.py` (v2, thinner
cards) is kept for reference.

### Updating an existing deployment
Replace these files (they are a matched set — a shared field spans all three):
`evaluator_library.json`, `logic.py`, `app.py`. `personalities.json` now includes
a **Silent Dropout** personality (used by FLW-02) — ship the updated copy.
`requirements.txt` is unchanged.
