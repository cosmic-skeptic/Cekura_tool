"""
app.py — Cekura Evaluator Builder (Streamlit)

Run:  streamlit run app.py

Self-contained: reads evaluator_library.json + personalities.json from the same
folder. No API calls, no database. The user configures a bot in the sidebar,
the engine (logic.py) resolves applicability/forks/derived-values/conditionals/
tokens, and the app shows ready-to-paste Cekura evaluator cards with copy areas
and download buttons (Markdown / JSON).
"""

import json
import streamlit as st

import logic

st.set_page_config(page_title="Cekura Evaluator Builder", page_icon="🧪",
                   layout="wide")

# --------------------------------------------------------------------------
# Load bundled data once
# --------------------------------------------------------------------------
@st.cache_data
def _load():
    return logic.load_library(), logic.load_personalities()

LIBRARY, PERSONALITIES = _load()

STAGES = ["PreDue", "PostDue", "Welcome"]
GOALS = ["NACH-reminder", "PTP-date", "Pay-now", "Info-feedback"]
CHANNELS = ["link", "app", "branch", "cash"]
COLLATERAL = ["unsecured", "vehicle", "gold", "property"]
DELINQUENCY = ["1st-bounce", "Chronic", "Broken-PTP"]

# Which goals make sense for which stage (soft guidance, not enforced hard)
STAGE_GOAL_HINT = {
    "PreDue": ["NACH-reminder"],
    "PostDue": ["PTP-date", "Pay-now"],
    "Welcome": ["Info-feedback"],
}


# --------------------------------------------------------------------------
# Sidebar — bot configuration
# --------------------------------------------------------------------------
st.sidebar.title("🛠 Bot Configuration")
st.sidebar.caption("Set your bot's parameters. The evaluator list on the right "
                   "updates automatically.")

with st.sidebar:
    st.subheader("Core")
    stage = st.selectbox("Stage", STAGES, index=1)
    goal_opts = GOALS
    default_goal = STAGE_GOAL_HINT.get(stage, GOALS)[0]
    goal = st.selectbox("Goal", goal_opts, index=goal_opts.index(default_goal))
    if goal not in STAGE_GOAL_HINT.get(stage, []):
        st.warning(f"‘{goal}’ is unusual for stage ‘{stage}’. "
                   "Cards will still be filtered by your exact selection.")

    company_name = st.text_input("Company name", "Muthoot Capital Services")
    persona = st.text_input("Agent persona (name + gender note)", "Priya (female)")
    toll_free = st.text_input("Support / toll-free number", "04847119400")

    st.subheader("Payment")
    payment_channels = st.multiselect("Payment channels", CHANNELS,
                                      default=["link", "app", "branch"])
    app_name = st.text_input("App name", "Muthoot Fincorp one",
                             disabled="app" not in payment_channels)
    branch_hours = st.text_input("Branch hours", "10 AM-2 PM",
                                 disabled="branch" not in payment_channels)

    ptp_relevant = goal in ("PTP-date", "Pay-now")
    ptp_window_days = st.number_input(
        "PTP window (max acceptable days)", min_value=0, max_value=365, value=2,
        step=1, disabled=not ptp_relevant,
        help="Used relatively: cards offer a date just beyond this (should be "
             "pushed) and one within it (should be accepted). 0 = today only.")

    st.subheader("Customer / loan")
    collateral_type = st.selectbox("Collateral type", COLLATERAL, index=0)
    delinquency = st.selectbox("Delinquency stage", DELINQUENCY, index=0,
                               disabled=stage != "PostDue")

    st.subheader("Language")
    lang_primary = st.text_input("Primary language", "Hindi")
    bilingual = st.checkbox("Bilingual (has a secondary language)", value=True)
    lang_secondary = st.text_input("Secondary language", "English",
                                   disabled=not bilingual)

    st.subheader("Safety")
    has_helpline = st.checkbox("Has a distress/self-harm helpline", value=True)
    helpline = st.text_input("Helpline (name + number)", "iCall 9152987821",
                             disabled=not has_helpline)

# assemble config
config = {
    "stage": stage,
    "goal": goal,
    "company_name": company_name,
    "persona": persona,
    "toll_free": toll_free,
    "payment_channels": payment_channels,
    "app_name": app_name if "app" in payment_channels else "",
    "branch_hours": branch_hours if "branch" in payment_channels else "",
    "ptp_window_days": ptp_window_days if ptp_relevant else "",
    "collateral_type": collateral_type,
    "delinquency": delinquency if stage == "PostDue" else "1st-bounce",
    "lang_primary": lang_primary,
    "lang_secondary": lang_secondary if bilingual else "",
    "helpline": helpline if has_helpline else "",
}

result = logic.build_evaluators(config, LIBRARY, PERSONALITIES)
included = result["included"]
excluded = result["excluded"]

# --------------------------------------------------------------------------
# Header + summary
# --------------------------------------------------------------------------
st.title("🧪 Cekura Evaluator Builder")
st.caption("Configure a bot → get ready-to-paste, fully-resolved Cekura "
           "evaluator cards. All logic runs locally; nothing is sent anywhere.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Evaluators included", len(included))
c2.metric("P0 (critical)", sum(1 for c in included if c["priority"] == "P0"))
c3.metric("Excluded (not applicable)", len(excluded))
unresolved_total = sum(len(c["unresolved_tokens"]) for c in included)
c4.metric("Unresolved tokens", unresolved_total,
          delta=None if unresolved_total == 0 else "check config",
          delta_color="inverse")

if unresolved_total:
    st.error("Some tokens couldn't be resolved from your config (shown in the "
             "affected cards). Fill the missing fields in the sidebar.")

# downloads
dl1, dl2, _ = st.columns([1, 1, 4])
dl1.download_button("⬇ Download all (Markdown)",
                    data=logic.to_markdown(result, config),
                    file_name="cekura_evaluators.md", mime="text/markdown")
dl2.download_button("⬇ Download all (JSON)",
                    data=logic.to_json_export(result, config),
                    file_name="cekura_evaluators.json", mime="application/json")

# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------
cats = sorted({c["category"] for c in included})
fcol1, fcol2 = st.columns([2, 1])
sel_cats = fcol1.multiselect("Filter by category", cats, default=cats)
p0_only = fcol2.toggle("P0 only", value=False)

view = [c for c in included
        if c["category"] in sel_cats and (not p0_only or c["priority"] == "P0")]

st.divider()

# --------------------------------------------------------------------------
# Evaluator cards
# --------------------------------------------------------------------------
tab_cards, tab_excluded, tab_config = st.tabs(
    [f"Evaluators ({len(view)})", f"Excluded ({len(excluded)})", "Resolved config"])

with tab_cards:
    if not view:
        st.info("No evaluators match the current filters.")
    for c in view:
        badge = "🔴" if c["priority"] == "P0" else "🟡"
        with st.expander(f"{badge} {c['id']} — {c['scenario']}  "
                         f"·  {c['category']}  ·  {c['priority']}",
                         expanded=False):
            pcol1, pcol2 = st.columns([1, 1])
            with pcol1:
                st.markdown(f"**Personality:** `{c['personality']}`")
            ps = c.get("personality_settings", {})
            if ps:
                with pcol2:
                    st.markdown(
                        f"**Settings:** interruption `{ps.get('interruption','')}` · "
                        f"speed `{ps.get('speed','')}` · noise `{ps.get('bg_noise','')}` · "
                        f"lang `{ps.get('lang','')}`")
            if c["unresolved_tokens"]:
                st.warning("Unresolved tokens: " + ", ".join(c["unresolved_tokens"]))

            st.markdown("**Instruction** (paste into Cekura scenario field)")
            st.code(c["instruction"], language=None)

            st.markdown("**Expected Outcome** (paste into Cekura expected-outcome field)")
            st.code(c["expected"], language=None)

            if ps.get("prompt"):
                st.markdown("**Personality prompt** (paste into Cekura Create-Personality)")
                st.code(ps["prompt"], language=None)

with tab_excluded:
    st.caption("These library cards were filtered OUT because they don't apply "
               "to this bot's configuration.")
    for e in excluded:
        st.markdown(f"- **{e['id']}** — {e['scenario']}  \n"
                    f"  <span style='color:gray'>{e['reason']}</span>",
                    unsafe_allow_html=True)

with tab_config:
    st.caption("The fully-resolved context the engine used (base + derived).")
    display_ctx = {k: v for k, v in result["context"].items()
                   if not k.startswith("_")}
    st.json(display_ctx)

st.divider()
st.caption("Cekura Evaluator Builder · v1 · library + personalities bundled as "
           "local JSON · edit those files to extend the library.")
