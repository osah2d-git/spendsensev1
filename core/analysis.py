"""All the arithmetic. The AI never calculates anything; it only reads these results."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .categorize import DISCRETIONARY, EXCLUDED, NEEDS_REVIEW, SPENDING_CATEGORIES

PAY_PERIODS_PER_YEAR = {"Weekly": 52, "Bi-weekly": 26, "Semi-monthly": 24, "Monthly": 12}


def monthly_income(amount: float | None, frequency: str) -> float | None:
    """Convert take-home pay per pay period to a monthly figure."""
    if not amount or amount <= 0:
        return None
    return round(amount * PAY_PERIODS_PER_YEAR[frequency] / 12, 2)


def spending(df: pd.DataFrame) -> pd.DataFrame:
    """Only money out that counts as spending, as positive dollar amounts."""
    s = df[~df["Category"].isin(EXCLUDED)].copy()
    s["Spent"] = -s["Amount"]
    return s


def totals_by_month(df: pd.DataFrame) -> pd.DataFrame:
    """Rows = categories, columns = months, values = dollars spent."""
    s = spending(df)
    order = [c for c in SPENDING_CATEGORIES + [NEEDS_REVIEW] if c in set(s["Category"])]
    t = s.pivot_table(index="Category", columns="Month", values="Spent", aggfunc="sum", fill_value=0.0)
    return t.reindex(order).round(2)


@dataclass
class Summary:
    latest: str
    previous: str | None
    months: list[str]
    totals: pd.DataFrame            # category x month
    latest_total: float
    previous_total: float | None
    change: pd.DataFrame            # per category: previous, latest, change $, change %
    income: float | None
    share_of_income: dict           # category -> % of monthly income (latest month)
    savings_rate: float | None      # % of income left after spending, latest month
    subscriptions: list[tuple[str, float]]  # (merchant, monthly cost) in latest month
    excluded_count: int
    incoming_count: int


def summarize(df: pd.DataFrame, income: float | None = None) -> Summary:
    totals = totals_by_month(df)
    months = sorted(totals.columns.tolist())
    latest = months[-1]
    previous = months[-2] if len(months) > 1 else None
    latest_total = round(float(totals[latest].sum()), 2)
    previous_total = round(float(totals[previous].sum()), 2) if previous else None
    rows = []
    for cat in totals.index:
        now = float(totals.at[cat, latest])
        before = float(totals.at[cat, previous]) if previous else None
        diff = None if before is None else round(now - before, 2)
        pct = None if not before else round((now - before) / before * 100, 1)
        rows.append({"Category": cat, "Previous month": before, "Latest month": round(now, 2),
                     "Change $": diff, "Change %": pct})
    change = pd.DataFrame(rows).set_index("Category")
    share = {}
    savings_rate = None
    if income:
        share = {cat: round(float(totals.at[cat, latest]) / income * 100, 1) for cat in totals.index}
        savings_rate = round((income - latest_total) / income * 100, 1)
    s = spending(df)
    subs = (s[(s["Category"] == "Subscriptions") & (s["Month"] == latest)]
            .groupby("Description")["Spent"].sum().round(2).sort_values(ascending=False))
    return Summary(latest=latest, previous=previous, months=months, totals=totals,
                   latest_total=latest_total, previous_total=previous_total, change=change,
                   income=income, share_of_income=share, savings_rate=savings_rate,
                   subscriptions=list(subs.items()),
                   excluded_count=int((df["Category"] == "Transfers (excluded)").sum()),
                   incoming_count=int((df["Category"] == "Money in (ignored)").sum()))


@dataclass
class Suggestion:
    kind: str           # "category" or "subscriptions"
    category: str
    action: str         # plain action, written by code (the fallback wording)
    monthly: float      # dollars saved per month, calculated here
    yearly: float
    share_of_income: float | None


def saving_suggestion(sm: Summary) -> Suggestion | None:
    """Pick the single saving with the largest yearly dollar value.

    Candidates:
      - a discretionary category that rose this month: return it to last month's level
      - subscriptions (3 or more): cancel the two cheapest ones
    """
    cands: list[Suggestion] = []
    if sm.previous:
        for cat in DISCRETIONARY:
            if cat in sm.change.index:
                diff = sm.change.at[cat, "Change $"]
                if diff and diff > 0:
                    m = round(diff, 2)
                    cands.append(Suggestion(
                        "category", cat,
                        f"Bring {cat.lower()} back to last month's level "
                        f"(${sm.change.at[cat, 'Previous month']:,.2f} instead of ${sm.change.at[cat, 'Latest month']:,.2f}).",
                        m, round(m * 12, 2), None))
    if len(sm.subscriptions) >= 3:
        cheapest = sorted(sm.subscriptions, key=lambda x: x[1])[:2]
        m = round(sum(a for _, a in cheapest), 2)
        names = " and ".join(n for n, _ in cheapest)
        cands.append(Suggestion(
            "subscriptions", "Subscriptions",
            f"You pay for {len(sm.subscriptions)} subscriptions (${sum(a for _, a in sm.subscriptions):,.2f} a month). "
            f"Cancelling two you rarely use saves at least ${m:,.2f} a month "
            f"(estimate based on your two cheapest: {names}).",
            m, round(m * 12, 2), None))
    if not cands:
        return None
    best = max(cands, key=lambda c: c.yearly)
    if sm.income:
        best.share_of_income = round(best.monthly / sm.income * 100, 1)
    return best


def facts_for_ai(sm: Summary, sug: Suggestion | None) -> dict:
    """The only data the AI sees: totals and percentages, no transactions, no income amount."""
    cats = {}
    for cat, r in sm.change.iterrows():
        if cat == NEEDS_REVIEW:
            continue
        item = {"latest_month_$": r["Latest month"]}
        if r["Previous month"] is not None and not pd.isna(r["Previous month"]):
            item["previous_month_$"] = r["Previous month"]
            item["change_$"] = r["Change $"]
            if r["Change %"] is not None and not pd.isna(r["Change %"]):
                item["change_%"] = r["Change %"]
        if cat in sm.share_of_income:
            item["share_of_income_%"] = sm.share_of_income[cat]
        cats[cat] = item
    facts = {"latest_month": sm.latest, "previous_month": sm.previous,
             "total_spending_latest_$": sm.latest_total, "total_spending_previous_$": sm.previous_total,
             "categories": cats, "number_of_subscriptions": len(sm.subscriptions)}
    if sm.savings_rate is not None:
        facts["savings_rate_%"] = sm.savings_rate
    if sug:
        facts["saving_suggestion"] = {"category": sug.category, "monthly_$": sug.monthly,
                                      "yearly_$": sug.yearly, "plain_action": sug.action}
        if sug.share_of_income is not None:
            facts["saving_suggestion"]["share_of_income_%"] = sug.share_of_income
    return facts


def allowed_numbers(facts: dict) -> set[float]:
    """Every number the AI may quote, plus simple roundings of each."""
    out: set[float] = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (int, float)) and x is not None and not (isinstance(x, float) and pd.isna(x)):
            v = abs(float(x))
            out.update({round(v, 2), round(v, 1), float(round(v)), float(int(v))})
        elif isinstance(x, str):
            import re
            for n in re.findall(r"\d[\d,]*\.?\d*", x):
                try:
                    v = float(n.replace(",", ""))
                    out.update({round(v, 2), round(v, 1), float(round(v))})
                except ValueError:
                    pass
    walk(facts)
    return out
