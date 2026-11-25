"""Read, check and combine uploaded bank CSV files.

SpendSense's own layout is Date, Description, Amount, Bank, with negative
amounts for money out. Real bank exports differ, so the loader also accepts:

- other column names (Transaction Date, CAD$, Description 1, Payee, ...)
- separate Debit and Credit (or Withdrawals and Deposits) columns
- files with no header row (TD and CIBC style: date, description, debit, credit)
- credit-card files where purchases are positive numbers: if most amounts in a
  file are positive, the signs are flipped, and the user can override this.

Any column that is not used (account numbers, balances, card numbers) is dropped
before anything else happens.
"""
from __future__ import annotations

import io
import re

import pandas as pd

MAX_ROWS = 20000
ACCOUNT_LIKE = re.compile(r"\b\d[\d\- ]{5,}\d\b")

ALIASES = {
    "date": ["date", "transaction date", "posted date", "date posted", "posting date", "trans. date",
             "trans date", "transaction_date"],
    "description": ["description", "description 1", "merchant", "payee", "name", "transaction description",
                    "details", "transaction details", "transaction", "merchant name"],
    "extra": ["description 2", "memo", "sub-description", "sub description"],
    "amount": ["amount", "cad$", "transaction amount", "amount (cad)", "amount cad", "cad"],
    "debit": ["debit", "debits", "withdrawals", "withdrawal", "money out", "debit amount", "withdrawal amount"],
    "credit": ["credit", "credits", "deposits", "deposit", "money in", "credit amount", "deposit amount"],
    "bank": ["bank", "institution", "account name"],
    # A column that says Debit or Credit for each row (Scotiabank, BMO chequing), used when amounts have no sign.
    "direction": ["type of transaction", "transaction type", "debit/credit", "dr/cr", "type"],
}
SPEND_WORDS = {"debit", "dr", "withdrawal", "purchase"}
INCOME_WORDS = {"credit", "cr", "deposit", "payment", "refund"}


class FileProblem(Exception):
    """A problem with one file, written so the user can act on it."""


def _clean_amount(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace("$", "").replace(",", "").replace(" ", "")
    if text == "" or text.lower() == "nan":
        return None
    if text.endswith("-"):
        text = "-" + text[:-1]
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _looks_like_date(text) -> bool:
    s = str(text).strip()
    if not re.search(r"\d", s):
        return False
    return not pd.isna(pd.to_datetime(s, errors="coerce"))


def _find(cols: dict[str, str], key: str) -> str | None:
    for a in ALIASES[key]:
        if a in cols:
            return cols[a]
    return None


def read_one(name: str, raw: bytes, flip: bool | None = None) -> tuple[pd.DataFrame, dict]:
    """Read one file into Date, Description, Amount, Bank.

    Returns (rows, info). info["flipped"] says whether signs were flipped and
    info["auto_flip"] what the automatic check decided. Raises FileProblem.
    """
    if not name.lower().endswith(".csv"):
        raise FileProblem(f"{name}: this is not a CSV file. Download your transactions as CSV from online banking.")
    if not raw or not raw.strip():
        raise FileProblem(f"{name}: the file is empty.")
    try:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, skipinitialspace=True, index_col=False)
    except Exception:
        raise FileProblem(f"{name}: the file could not be read as a CSV table.")
    if len(df.columns) and _looks_like_date(df.columns[0]):
        # No header row (TD, CIBC): date, description, debit, credit[, balance or card number]
        df = pd.read_csv(io.BytesIO(raw), dtype=str, header=None, skipinitialspace=True, index_col=False)
        if df.shape[1] < 3:
            raise FileProblem(f"{name}: the file has no column names and fewer than 3 columns, so it can't be read.")
        names = ["Date", "Description", "Debit", "Credit"] if df.shape[1] >= 4 else ["Date", "Description", "Amount"]
        df = df.iloc[:, :len(names)]
        df.columns = names
    df.columns = [str(c).strip() for c in df.columns]
    cols = {c.lower(): c for c in df.columns}
    c_date, c_desc = _find(cols, "date"), _find(cols, "description")
    c_amt, c_deb, c_cred = _find(cols, "amount"), _find(cols, "debit"), _find(cols, "credit")
    missing = []
    if not c_date:
        missing.append("Date")
    if not c_desc:
        missing.append("Description")
    if not c_amt and not (c_deb or c_cred):
        missing.append("Amount")
    if missing:
        raise FileProblem(f"{name}: missing the column{'s' if len(missing) > 1 else ''} {', '.join(missing)}. "
                          "The file needs a date, a description and either an Amount column or Debit and Credit columns. "
                          f"Columns found: {', '.join(df.columns[:8])}.")
    if len(df) == 0:
        raise FileProblem(f"{name}: the file has column names but no transactions.")
    if len(df) > MAX_ROWS:
        raise FileProblem(f"{name}: {len(df):,} rows is more than the {MAX_ROWS:,} this prototype handles.")

    desc = df[c_desc].fillna("").astype(str).str.strip()
    c_extra = _find(cols, "extra")
    if c_extra:
        extra = df[c_extra].fillna("").astype(str).str.strip()
        desc = (desc + " " + extra).str.strip()

    info = {"file": name, "auto_flip": False, "flipped": False, "debit_credit": False, "direction": None}
    c_dir = _find(cols, "direction")
    words = df[c_dir].fillna("").astype(str).str.strip().str.lower() if c_dir else None
    use_dir = (c_amt is not None and words is not None
               and words.isin(SPEND_WORDS | INCOME_WORDS).mean() > 0.8)
    if use_dir:
        # Amounts are unsigned; the Debit/Credit column says which way the money went.
        amount = df[c_amt].map(_clean_amount).abs()
        amount = amount.where(~words.isin(SPEND_WORDS), -amount)
        info["direction"] = c_dir
    elif c_amt:
        amount = df[c_amt].map(_clean_amount)
        nonzero = amount.dropna()
        nonzero = nonzero[nonzero != 0]
        info["auto_flip"] = bool(len(nonzero) and (nonzero > 0).mean() > 0.6)
        info["flipped"] = info["auto_flip"] if flip is None else flip
        if info["flipped"]:
            amount = -amount
    else:
        deb = df[c_deb].map(_clean_amount).fillna(0).abs() if c_deb else 0
        cred = df[c_cred].map(_clean_amount).fillna(0).abs() if c_cred else 0
        amount = cred - deb
        both_empty = (df[c_deb].isna() if c_deb else True) & (df[c_cred].isna() if c_cred else True)
        amount = amount.where(~both_empty, None)
        info["debit_credit"] = True

    out = pd.DataFrame({"Date": df[c_date], "Description": desc, "Amount": amount})
    c_bank = _find(cols, "bank")
    fallback = name.rsplit(".", 1)[0]
    out["Bank"] = df[c_bank].fillna(fallback) if c_bank else fallback
    out["Description"] = out["Description"].str.replace(ACCOUNT_LIKE, "####", regex=True)
    out["Source file"] = name
    return out, info


def combine(files: list[tuple[str, bytes]], flips: dict[str, bool] | None = None):
    """Combine several files. Returns (transactions, problems, notes, infos)."""
    flips = flips or {}
    frames, problems, notes, infos = [], [], [], []
    for name, raw in files:
        try:
            rows, info = read_one(name, raw, flips.get(name))
            frames.append(rows)
            infos.append(info)
        except FileProblem as e:
            problems.append(str(e))
    if not frames:
        return (pd.DataFrame(columns=["Date", "Description", "Amount", "Bank", "Source file"]),
                problems, notes, infos)
    df = pd.concat(frames, ignore_index=True)
    df["Amount"] = pd.to_numeric(df["Amount"].map(lambda v: _clean_amount(v) if not isinstance(v, float) else v),
                                 errors="coerce")
    df["Date"] = pd.to_datetime(df["Date"].astype(str).str.strip(), errors="coerce", format="mixed")
    bad = df["Amount"].isna() | df["Date"].isna()
    if bad.any():
        notes.append(f"{int(bad.sum())} row(s) skipped because the date or amount could not be read.")
    df = df[~bad].copy()
    df = df.sort_values("Date", kind="stable").reset_index(drop=True)
    df["Month"] = df["Date"].dt.to_period("M").astype(str)
    return df, problems, notes, infos
