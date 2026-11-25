"""Automated checks for the planted answers in the made-up sample files.

Run:  python -m pytest -q
These cover the parts calculated in code. The click-through tests in PRD.md
cover the screen and the AI.
"""
from pathlib import Path

import pytest

from core import ai
from core.analysis import (allowed_numbers, facts_for_ai, monthly_income, saving_suggestion,
                           summarize)
from core.categorize import INCOMING, NEEDS_REVIEW, TRANSFERS, apply_rules
from core.loader import combine

DATA = Path(__file__).resolve().parent.parent / "data"


def load(*names, folder="sample"):
    tx, problems, notes, _ = combine([(n, (DATA / folder / n).read_bytes()) for n in names])
    return tx, problems, notes


@pytest.fixture
def priya():
    tx, problems, notes = load("priya_northern_chequing.csv", "priya_prairie_visa.csv")
    assert problems == []
    return apply_rules(tx)


@pytest.fixture
def sam():
    tx, _, _ = load("sam_bowvalley_chequing.csv", "sam_chinook_mastercard.csv")
    return apply_rules(tx)


def test_two_banks_combine_to_65_rows_without_account_numbers(priya):
    assert len(priya) == 65
    assert set(priya["Bank"]) == {"Northern Bank Chequing", "Prairie Visa"}
    assert "Account Number" not in priya.columns
    assert not priya.astype(str).apply(lambda c: c.str.contains("3456789")).any().any()


def test_subscriptions_total_87_in_march(priya):
    sm = summarize(priya)
    assert sm.totals.at["Subscriptions", "2026-03"] == pytest.approx(87.00)


def test_dining_rises_437_to_612(priya):
    sm = summarize(priya)
    r = sm.change.loc["Dining Out"]
    assert r["Previous month"] == pytest.approx(437.00)
    assert r["Latest month"] == pytest.approx(612.00)
    assert r["Change %"] == pytest.approx(40.0)


def test_unknown_merchant_needs_review_then_user_fix_updates_total(priya):
    row = priya["Description"] == "SQ *MOUNTAIN BREW"
    assert (priya.loc[row, "Category"] == NEEDS_REVIEW).all()
    priya.loc[row, "Category"] = "Dining Out"
    sm = summarize(priya)
    assert sm.totals.at["Dining Out", "2026-03"] == pytest.approx(618.75)


def test_card_payment_is_excluded_and_income_ignored(priya):
    pay = priya[priya["Description"] == "PAYMENT - PRAIRIE VISA"]
    assert (pay["Category"] == TRANSFERS).all()
    received = priya[priya["Description"] == "PAYMENT RECEIVED - THANK YOU"]
    assert (received["Category"] == TRANSFERS).all()
    payroll = priya[priya["Description"].str.startswith("PAYROLL")]
    assert (payroll["Category"] == INCOMING).all()
    sm = summarize(priya)
    # total spending must not include the 1,250 card payment
    spent_march = -priya[(priya["Month"] == "2026-03") & (priya["Amount"] < 0)
                         & (priya["Category"] != TRANSFERS)]["Amount"].sum()
    assert sm.latest_total == pytest.approx(round(spent_march, 2))


def test_income_conversion_and_share():
    assert monthly_income(2000, "Bi-weekly") == pytest.approx(4333.33)
    assert monthly_income(1000, "Weekly") == pytest.approx(4333.33)
    assert monthly_income(2500, "Semi-monthly") == pytest.approx(5000.00)
    assert monthly_income(0, "Monthly") is None


def test_share_of_income_dining(priya):
    sm = summarize(priya, monthly_income(2000, "Bi-weekly"))
    assert sm.share_of_income["Dining Out"] == pytest.approx(14.1)
    assert sm.savings_rate == pytest.approx(round((4333.33 - sm.latest_total) / 4333.33 * 100, 1))


def test_suggestion_priya_is_dining(priya):
    s = saving_suggestion(summarize(priya))
    assert s.category == "Dining Out"
    assert s.monthly == pytest.approx(175.00) and s.yearly == pytest.approx(2100.00)


def test_suggestion_sam_is_subscriptions(sam):
    s = saving_suggestion(summarize(sam))
    assert s.category == "Subscriptions"
    assert s.monthly == pytest.approx(3.99 + 11.99)


@pytest.mark.parametrize("name,words", [
    ("statement.pdf", "not a CSV"),
    ("missing_amount.csv", "missing the column Amount"),
    ("empty.csv", "empty"),
])
def test_bad_files_give_plain_messages(name, words):
    tx, problems, _ = load(name, folder="bad")
    assert tx.empty
    assert len(problems) == 1 and words in problems[0]


def test_odd_amounts_are_cleaned_or_skipped():
    tx, problems, notes = load("odd_amounts.csv", folder="bad")
    assert problems == []
    assert len(tx) == 2  # "$4.50-" becomes -4.50; "abc" and "not a date" are skipped
    assert sorted(tx["Amount"]) == [-12.99, -4.50]
    assert "2 row(s) skipped" in notes[0]


def test_large_file():
    tx, problems, _ = load("large_2000_rows.csv", folder="bad")
    assert problems == [] and len(tx) == 2000


def test_number_check_blocks_made_up_numbers(priya):
    sm = summarize(priya)
    facts = facts_for_ai(sm, saving_suggestion(sm))
    ok = allowed_numbers(facts)
    assert ai.numbers_ok("Dining out grew from $437.00 to $612.00, up 40.0%.", ok)
    assert not ai.numbers_ok("Dining out grew to $700.00.", ok)
    assert not ai.safe("Put the savings into a TFSA.", ok)


def test_ai_unavailable_without_key(monkeypatch, priya):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(ai, "get_api_key", lambda: None)
    assert ai.suggest_categories(["SQ *MOUNTAIN BREW"]) is None
    assert ai.write_insights({"a": 1}, {1.0}) is None
    assert "no API key found" in ai.last_error


def test_ai_error_reason_is_reported(monkeypatch):
    import anthropic
    import httpx2 as httpx
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.AuthenticationError("invalid x-api-key", response=httpx.Response(401, request=req), body=None)

    class Boom:
        class messages:
            @staticmethod
            def create(**k):
                raise err
    monkeypatch.setattr(ai, "get_api_key", lambda: "sk-ant-test")
    monkeypatch.setattr(ai, "_client", lambda: Boom)
    assert ai.write_insights({"a": 1}, {1.0}) is None
    assert "API key was rejected" in ai.last_error


def test_ai_output_is_filtered(monkeypatch, priya):
    sm = summarize(priya)
    facts = facts_for_ai(sm, saving_suggestion(sm))
    fake = ('{"insights": ["Dining out grew 40.0% to $612.00.", "You spent $999.99 on fun.", '
            '"Consider investing in an ETF."], "suggestion": "Try bringing dining back to $437.00 to save $2,100.00 a year."}')
    monkeypatch.setattr(ai, "_ask", lambda *a, **k: fake)
    out = ai.write_insights(facts, allowed_numbers(facts))
    assert out["insights"] == ["Dining out grew 40.0% to $612.00."]
    assert out["dropped"] == 2
    assert out["suggestion"].startswith("Try bringing")


# ---------- real bank export layouts ----------

def one(name, text, flip=None):
    tx, problems, notes, infos = combine([(name, text.encode())], {name: flip} if flip is not None else None)
    return tx, problems, infos


def test_credit_card_with_positive_purchases_is_flipped():
    text = ("Date,Description,Amount\n2026-03-01,STARBUCKS,5.25\n2026-03-02,SAFEWAY,80.10\n"
            "2026-03-03,NETFLIX.COM,20.99\n2026-03-20,PAYMENT THANK YOU,-106.34\n")
    tx, problems, infos = one("visa.csv", text)
    tx = apply_rules(tx)
    assert infos[0]["flipped"] is True
    assert (tx["Category"] == INCOMING).sum() == 0
    assert set(tx["Category"]) >= {"Dining Out", "Groceries", "Subscriptions", TRANSFERS}


def test_user_can_override_the_sign():
    text = "Date,Description,Amount\n2026-03-01,STARBUCKS,5.25\n2026-03-02,SAFEWAY,80.10\n"
    tx, _, infos = one("x.csv", text, flip=False)
    assert infos[0]["flipped"] is False and (tx["Amount"] > 0).all()


def test_rbc_style_columns():
    text = ('"Account Type","Account Number","Transaction Date","Cheque Number","Description 1","Description 2","CAD$","USD$"\n'
            'Chequing,01234-5678901,3/2/2026,,SAFEWAY #8890,CALGARY AB,-54.20,\n'
            'Chequing,01234-5678901,3/5/2026,,PAYROLL DEP,,3100.00,\n')
    tx, problems, infos = one("rbc.csv", text)
    assert problems == [] and len(tx) == 2
    assert tx.loc[0, "Description"] == "SAFEWAY #8890 CALGARY AB" and tx.loc[0, "Amount"] == -54.20
    assert not tx.astype(str).apply(lambda c: c.str.contains("5678901")).any().any()


def test_td_style_no_header_debit_credit():
    text = ("03/02/2026,SAFEWAY #8890,54.20,,1200.00\n"
            "03/05/2026,PAYROLL DEP,,3100.00,4300.00\n"
            "03/09/2026,TIM HORTONS #4412,4.50,,4295.50\n")
    tx, problems, infos = one("td.csv", text)
    assert problems == [] and len(tx) == 3
    assert sorted(tx["Amount"]) == [-54.20, -4.50, 3100.00]
    assert infos[0]["debit_credit"]


def test_bmo_style_spaces_and_compact_dates():
    text = ("Item #,Card #,Transaction Date,Posting Date,Transaction Amount,Description\n"
            "1,'5191230012345678',20260302,20260303,45.10,EARLS KITCHEN + BAR\n"
            "2,'5191230012345678',20260304,20260305,12.99,SPOTIFY\n"
            "3,'5191230012345678',20260310,20260310,-58.09,PAYMENT RECEIVED - THANK YOU\n")
    tx, problems, infos = one("bmo.csv", text)
    tx = apply_rules(tx)
    assert problems == [] and len(tx) == 3
    assert str(tx.loc[0, "Date"].date()) == "2026-03-02"
    assert list(tx["Category"]) == ["Dining Out", "Subscriptions", TRANSFERS]


def test_withdrawals_and_deposits_columns():
    text = "Date,Description,Withdrawals,Deposits,Balance\n2026-03-02,SAFEWAY,54.20,,100\n2026-03-03,PAY,,500,600\n"
    tx, problems, _ = one("bank.csv", text)
    assert sorted(tx["Amount"]) == [-54.20, 500.0]
