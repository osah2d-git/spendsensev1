"""Sort transactions into categories with plain merchant rules.

Rules run first and never need the AI. Anything the rules cannot place is
marked NEEDS_REVIEW, and the app may then ask Claude for a suggestion.
"""
from __future__ import annotations

import re

import pandas as pd

SPENDING_CATEGORIES = [
    "Housing", "Groceries", "Dining Out", "Transport", "Subscriptions", "Shopping",
    "Utilities & Phone", "Health & Personal", "Entertainment", "Other",
]
TRANSFERS = "Transfers (excluded)"
INCOMING = "Money in (ignored)"
NEEDS_REVIEW = "Needs review"
ALL_CHOICES = SPENDING_CATEGORIES + [TRANSFERS, NEEDS_REVIEW]
# Categories that are never counted as spending.
EXCLUDED = {TRANSFERS, INCOMING}
# Categories a person can usually cut back on. Used for saving suggestions.
DISCRETIONARY = ["Dining Out", "Shopping", "Entertainment"]

# (pattern, category). First match wins, so specific rules go first.
RULES: list[tuple[str, str]] = [
    # transfers between the user's own accounts and card payments
    (r"\bPAYMENT\s*-\s*.*(VISA|MASTERCARD|AMEX|CARD)\b", TRANSFERS),
    (r"PAYMENT RECEIVED|THANK YOU", TRANSFERS),
    (r"\bTRANSFER (TO|FROM)\b|\bTFR\b|OWN ACCOUNT", TRANSFERS),
    # subscriptions
    (r"NETFLIX|SPOTIFY|DISNEY|CRAVE|AUDIBLE|APPLE\.COM/BILL|ICLOUD|XBOX|PLAYSTATION|PARAMOUNT|PRIME VIDEO|YOUTUBE|GOODLIFE|PATREON", "Subscriptions"),
    # housing
    (r"\bRENT\b|MORTGAGE|CONDO FEE|PROPERTY TAX", "Housing"),
    # utilities and phone
    (r"ENMAX|ATCO|EPCOR|DIRECT ENERGY|TELUS|ROGERS|BELL CANADA|FIDO|KOODO|SHAW|FREEDOM MOBILE", "Utilities & Phone"),
    # groceries
    (r"SAFEWAY|SUPERSTORE|SOBEYS|CO-OP|NO FRILLS|COSTCO|WALMART|T&T|FRESHCO|SAVE ON FOODS", "Groceries"),
    # dining
    (r"TIM HORTONS|STARBUCKS|A&W|MCDONALD|EARLS|PHO |SKIP THE DISHES|UBER EATS|DOORDASH|RESTAURANT|PIZZA|SUSHI|CAFE|COFFEE|BAR\b|KITCHEN", "Dining Out"),
    # transport
    (r"CALGARY TRANSIT|PETRO-CANADA|SHELL|ESSO|HUSKY|UBER(?! EATS)|LYFT|PARKING|IMPARK", "Transport"),
    # health and personal
    (r"SHOPPERS DRUG|REXALL|LONDON DRUGS|PHARMACY|DENTAL|CLINIC|SALON|BARBER", "Health & Personal"),
    # shopping
    (r"AMAZON|INDIGO|SPORT CHEK|BEST BUY|WINNERS|IKEA|CANADIAN TIRE|H&M|ZARA|LULULEMON", "Shopping"),
    # entertainment
    (r"CINEPLEX|TICKETMASTER|STEAM|BOWLING|THEATRE|CONCERT", "Entertainment"),
]
_COMPILED = [(re.compile(p, re.I), c) for p, c in RULES]


def rule_category(description: str, amount: float) -> str:
    if amount > 0:
        # Card payments received show as money in on the card; they are transfers either way.
        for rx, cat in _COMPILED:
            if cat == TRANSFERS and rx.search(description):
                return TRANSFERS
        return INCOMING
    for rx, cat in _COMPILED:
        if rx.search(description):
            return cat
    return NEEDS_REVIEW


def apply_rules(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Category"] = [rule_category(d, a) for d, a in zip(df["Description"], df["Amount"])]
    df["Source"] = "Rule"
    df.loc[df["Category"] == NEEDS_REVIEW, "Source"] = "Unplaced"
    df.loc[df["Category"] == INCOMING, "Source"] = "Money in"
    return df


def unplaced_merchants(df: pd.DataFrame) -> list[str]:
    return sorted(df.loc[df["Category"] == NEEDS_REVIEW, "Description"].unique().tolist())
