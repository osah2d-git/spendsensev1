"""SpendSense: see where your money went across all your banks, and get one saving idea.

Run locally:  streamlit run app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core import ai
from core.analysis import (PAY_PERIODS_PER_YEAR, allowed_numbers, facts_for_ai, monthly_income,
                           saving_suggestion, summarize)
from core.categorize import (ALL_CHOICES, EXCLUDED, INCOMING, MISC, TRANSFERS, apply_rules,
                             finish_unplaced, unplaced_merchants)
from core.loader import combine

load_dotenv()
st.set_page_config(page_title="SpendSense", page_icon="💡", layout="wide")

SAMPLES = {
    "Priya (dining grew this month)": ["priya_northern_chequing.csv", "priya_prairie_visa.csv"],
    "Sam (many subscriptions)": ["sam_bowvalley_chequing.csv", "sam_chinook_mastercard.csv"],
}
SAMPLE_DIR = Path(__file__).parent / "data" / "sample"
DISCLAIMER = ("SpendSense is a course prototype that gives educational spending insights, "
              "not financial advice. It does not give investment, credit or tax advice.")

st.markdown("""
<style>
.card {border:1px solid rgba(128,128,128,.35); border-radius:8px; padding:14px 16px; margin-bottom:10px;}
.card.suggest {border:2px solid #1c7c54; background:rgba(28,124,84,.07);}
.tag {font-size:12px; opacity:.75;}
</style>""", unsafe_allow_html=True)


# ---------- state ----------
def load_files(files: list[tuple[str, bytes]], flips: dict | None = None):
    st.session_state.files = files
    st.session_state.flips = flips or {}
    tx, problems, notes, infos = combine(files, st.session_state.flips)
    st.session_state.problems = problems
    st.session_state.notes = notes
    st.session_state.infos = infos
    st.session_state.ai_cache = {}
    if tx.empty:
        st.session_state.tx = None
        return
    tx = apply_rules(tx)
    st.session_state.ai_categories = "off"
    st.session_state.ai_cat_error = None
    unplaced = unplaced_merchants(tx)
    if unplaced:
        placed = ai.suggest_categories(unplaced)
        if placed is None:
            st.session_state.ai_categories = "unavailable"
            st.session_state.ai_cat_error = ai.last_error
        else:
            st.session_state.ai_categories = "on"
            for desc, cat in placed.items():
                mask = tx["Description"] == desc
                tx.loc[mask, "Category"] = cat
                tx.loc[mask, "Source"] = "AI-suggested"
    st.session_state.tx = finish_unplaced(tx)


for k, v in {"tx": None, "problems": [], "notes": [], "ai_cache": {}, "ai_categories": "off", "files": [],
             "flips": {}, "infos": [], "ai_cat_error": None}.items():
    st.session_state.setdefault(k, v)

# ---------- sidebar: income ----------
with st.sidebar:
    st.header("Your take-home pay")
    st.caption("Optional. Used only to show spending as a share of income. It is never sent to the AI.")
    pay = st.number_input("Net pay per pay period ($)", min_value=0.0, step=50.0, value=0.0, format="%.2f")
    freq = st.selectbox("How often are you paid?", list(PAY_PERIODS_PER_YEAR), index=1)
    income = monthly_income(pay, freq)
    if income:
        st.metric("Monthly take-home pay", f"${income:,.2f}")
    st.divider()
    st.caption("AI: Claude" + (" (connected)" if ai.get_api_key() else " (no API key, AI features off)"))
    st.caption(DISCLAIMER)

# ---------- header and upload ----------
st.title("SpendSense")
st.write("Upload one CSV file per bank. See where your money went across all of them, "
         "and get one realistic saving idea.")

c1, c2 = st.columns([3, 2])
with c1:
    uploads = st.file_uploader("Bank CSV files (columns: Date, Description, Amount, Bank)",
                               accept_multiple_files=True)
    if st.button("Analyze my files", type="primary", disabled=not uploads):
        load_files([(f.name, f.getvalue()) for f in uploads])
with c2:
    st.write("**No files?** Try made-up sample data:")
    for label, names in SAMPLES.items():
        if st.button(label, use_container_width=True):
            load_files([(n, (SAMPLE_DIR / n).read_bytes()) for n in names])

for p in st.session_state.problems:
    st.error(p)

tx: pd.DataFrame | None = st.session_state.tx
if tx is None:
    st.info("Nothing loaded yet. Your files stay in this browser session only and are cleared when you reload the page.")
    st.stop()

# ---------- notes about what was excluded ----------
n_in = int((tx["Category"] == INCOMING).sum())
n_tr = int((tx["Category"] == TRANSFERS).sum())
banks = ", ".join(sorted(tx["Bank"].astype(str).unique()))
st.success(f"Combined {len(tx)} transactions from {tx['Bank'].nunique()} account(s): {banks}.")
msgs = []
if n_in:
    msgs.append(f"{n_in} incoming transaction(s) (pay, refunds, money received) were ignored.")
if n_tr:
    msgs.append(f"{n_tr} card payment(s) or transfer(s) between your own accounts were excluded so nothing is counted twice.")
for n in st.session_state.notes + msgs:
    st.caption("ℹ️ " + n)

# How each file was read, with a way to fix the sign if the automatic check got it wrong.
with st.expander("How your files were read", expanded=any(i["flipped"] for i in st.session_state.infos)):
    st.caption("Banks write spending differently. Chequing accounts usually show it as negative numbers; "
               "many credit cards show purchases as positive numbers. If a file's spending shows up as "
               "\"Money in (ignored)\", change its setting here.")
    new_flips = dict(st.session_state.flips)
    for info in st.session_state.infos:
        if info["debit_credit"]:
            st.write(f"**{info['file']}**: separate Debit and Credit columns (Debit = spending).")
            continue
        if info["direction"]:
            st.write(f"**{info['file']}**: the \"{info['direction']}\" column says Debit (spending) or Credit "
                     "(payments and refunds, ignored).")
            continue
        options = ["Negative numbers (e.g. -45.00)", "Positive numbers (e.g. 45.00)"]
        choice = st.radio(f"In **{info['file']}**, spending is shown as:", options,
                          index=1 if info["flipped"] else 0, horizontal=True, key=f"flip_{info['file']}")
        new_flips[info["file"]] = choice == options[1]
    if any(new_flips.get(i["file"], i["flipped"]) != i["flipped"] for i in st.session_state.infos
           if not i["debit_credit"] and not i["direction"]):
        load_files(st.session_state.files, new_flips)
        st.rerun()

if st.session_state.ai_categories == "unavailable":
    st.warning("AI category suggestions are unavailable, so merchants the rules could not place were put in "
               "Miscellaneous (tagged Unplaced). You can set their category in the table.  \n"
               f"**Reason:** {st.session_state.ai_cat_error or 'unknown'}")

spend_rows = tx[~tx["Category"].isin(EXCLUDED)]
if len(spend_rows):
    by_rule = (spend_rows["Source"].isin(["Rule", "You"]) & (spend_rows["Category"] != MISC)).mean()
    by_ai = (spend_rows["Source"] == "AI-suggested").mean()
    unplaced = (spend_rows["Source"] == "Unplaced").mean()
    st.caption(f"Categorized: {by_rule:.0%} by merchant rules, {by_ai:.0%} by Claude, "
               f"{unplaced:.0%} unplaced (in Miscellaneous, tagged Unplaced).")

# ---------- transactions with editable categories ----------
st.subheader("1. Check the categories")
st.caption("Change any category in the Category column. Totals below update straight away.")
show = tx[["Date", "Description", "Amount", "Bank", "Category", "Source"]].copy()
show["Date"] = show["Date"].dt.date
review_first = st.toggle("Show only items to review (Unplaced or AI-suggested)", value=False)
view = show[show["Source"].isin(["Unplaced", "AI-suggested"])] if review_first else show
edited = st.data_editor(
    view, key=f"editor_{review_first}", hide_index=True, use_container_width=True, height=320,
    disabled=["Date", "Description", "Amount", "Bank", "Source"],
    column_config={
        "Amount": st.column_config.NumberColumn(format="dollar"),
        "Category": st.column_config.SelectboxColumn(options=ALL_CHOICES + [INCOMING], required=True),
        "Source": st.column_config.TextColumn("Tag", help="Rule, AI-suggested, Unplaced, Money in, or You"),
    },
)
changed = edited["Category"] != view["Category"]
if changed.any():
    idx = edited.index[changed]
    tx.loc[idx, "Category"] = edited.loc[idx, "Category"]
    tx.loc[idx, "Source"] = "You"
    st.session_state.tx = tx
    st.session_state.ai_cache = {}
    st.rerun()

# ---------- totals ----------
sm = summarize(tx, income)
st.subheader(f"2. Where your money went in {pd.Period(sm.latest).strftime('%B %Y')}")
m1, m2, m3 = st.columns(3)
delta = None if sm.previous_total is None else f"{sm.latest_total - sm.previous_total:+,.2f} vs last month"
m1.metric("Total spending", f"${sm.latest_total:,.2f}", delta, delta_color="inverse")
if income:
    m2.metric("Share of take-home pay", f"{sm.latest_total / income * 100:.1f}%")
    m3.metric("Savings rate", f"{sm.savings_rate:.1f}%", help="(Take-home pay - spending) / take-home pay, this month")
else:
    m2.metric("Months loaded", len(sm.months))
    m3.metric("Categories", len(sm.totals.index))

latest = sm.totals[sm.latest].reset_index()
latest.columns = ["Category", "Spent"]
latest = latest[latest["Spent"] > 0]
chart = (alt.Chart(latest).mark_bar(color="#1c7c54")
         .encode(x=alt.X("Spent:Q", title="Dollars", axis=alt.Axis(format="$,.0f")),
                 y=alt.Y("Category:N", sort="-x", title=None),
                 tooltip=["Category", alt.Tooltip("Spent:Q", format="$,.2f")])
         .properties(height=40 + 28 * len(latest)))
st.altair_chart(chart, use_container_width=True)

table = sm.change.copy().astype(float)
if income:
    table["Share of income %"] = pd.Series(sm.share_of_income)
fmt = {"Previous month": "${:,.2f}", "Latest month": "${:,.2f}", "Change $": "{:+,.2f}", "Change %": "{:+.1f}%",
       "Share of income %": "{:.1f}%"}
st.dataframe(table.style.format({k: v for k, v in fmt.items() if k in table.columns}, na_rep="–"),
             use_container_width=True)

# ---------- insights and suggestion ----------
st.subheader("3. What stands out")
sug = saving_suggestion(sm)
facts = facts_for_ai(sm, sug)
allowed = allowed_numbers(facts)
key = json.dumps(facts, sort_keys=True, default=str)
if key not in st.session_state.ai_cache:
    with st.spinner("Claude is writing your insights..."):
        st.session_state.ai_cache[key] = (ai.write_insights(facts, allowed), ai.last_error)
result, ai_error = st.session_state.ai_cache[key]

if result is None:
    st.warning("AI insights are unavailable right now. Your totals, chart and saving estimate are still correct.  \n"
               f"**Reason:** {ai_error or 'unknown'}")
    if st.button("Retry AI insights"):
        st.session_state.ai_cache.pop(key, None)
        st.rerun()
else:
    cols = st.columns(2)
    for i, text in enumerate(result["insights"]):
        cols[i % 2].markdown(f'<div class="card">{text}</div>', unsafe_allow_html=True)
    if result["dropped"]:
        st.caption(f"{result['dropped']} AI insight(s) were hidden because a number in them did not match your totals.")

st.subheader("4. One thing to try")
if sug is None:
    st.info("No clear saving stands out this month: no flexible category grew and you have fewer than three subscriptions.")
else:
    words = (result or {}).get("suggestion") or sug.action
    extra = f" · {sug.share_of_income:.1f}% of take-home pay" if sug.share_of_income is not None else ""
    st.markdown(
        f'<div class="card suggest"><b>{sug.category}</b><br>{words}<br><br>'
        f'<b>Estimated saving: ${sug.monthly:,.2f} a month · ${sug.yearly:,.2f} a year{extra}</b><br>'
        f'<span class="tag">Calculated from your transactions. {DISCLAIMER}</span></div>',
        unsafe_allow_html=True)
