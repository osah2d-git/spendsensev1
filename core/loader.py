"""Read, check and combine uploaded bank CSV files.

The standard layout is four columns: Date, Description, Amount, Bank.
Negative Amount = money out (spending). Positive Amount = money in, which
SpendSense ignores. Any other column (for example an account number) is
dropped before anything else happens.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pandas as pd

REQUIRED = ["Date", "Description", "Amount"]
MAX_ROWS = 20000
# A run of 7+ digits (optionally broken by dashes or spaces) looks like an account or card number.
ACCOUNT_LIKE = re.compile(r"\b\d[\d\- ]{5,}\d\b")


class FileProblem(Exception):
    """A problem with one file, written so the user can act on it."""


@dataclass
class LoadResult:
    transactions: pd.DataFrame
    notes: list[str] = field(default_factory=list)


def _clean_amount(value) -> float | None:
    if pd.isna(value):
        return None
    text = str(value).strip().replace("$", "").replace(",", "")
    if text.endswith("-"):  # some banks write 4.50-
        text = "-" + text[:-1]
    if text.startswith("(") and text.endswith(")"):  # (4.50) means negative
        text = "-" + text[1:-1]
    try:
        return float(text)
    except ValueError:
        return None


def read_one(name: str, raw: bytes, default_bank: str | None = None) -> pd.DataFrame:
    """Read one file into the standard columns, or raise FileProblem."""
    if not name.lower().endswith(".csv"):
        raise FileProblem(f"{name}: this is not a CSV file. Download your transactions as CSV from online banking.")
    if not raw or not raw.strip():
        raise FileProblem(f"{name}: the file is empty.")
    try:
        df = pd.read_csv(io.BytesIO(raw), dtype=str)
    except Exception:
        raise FileProblem(f"{name}: the file could not be read as a CSV table.")
    df.columns = [str(c).strip() for c in df.columns]
    lower = {c.lower(): c for c in df.columns}
    missing = [c for c in REQUIRED if c.lower() not in lower]
    if missing:
        raise FileProblem(f"{name}: missing the column{'s' if len(missing) > 1 else ''} {', '.join(missing)}. "
                          "The file needs Date, Description and Amount (Bank is optional).")
    if len(df) == 0:
        raise FileProblem(f"{name}: the file has column names but no transactions.")
    if len(df) > MAX_ROWS:
        raise FileProblem(f"{name}: {len(df):,} rows is more than the {MAX_ROWS:,} this prototype handles.")
    out = pd.DataFrame({
        "Date": df[lower["date"]],
        "Description": df[lower["description"]].fillna("").astype(str).str.strip(),
        "Amount": df[lower["amount"]],
    })
    bank_col = lower.get("bank")
    fallback = default_bank or name.rsplit(".", 1)[0]
    out["Bank"] = df[bank_col].fillna(fallback) if bank_col else fallback
    # Drop every other column (account numbers etc.) by construction, and mask number-like runs.
    out["Description"] = out["Description"].str.replace(ACCOUNT_LIKE, "####", regex=True)
    out["Source file"] = name
    return out


def combine(files: list[tuple[str, bytes]]) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Combine several files. Returns (transactions, problems, notes).

    Problems are per-file errors (the file is skipped). Notes describe rows that
    were skipped inside otherwise good files.
    """
    frames, problems, notes = [], [], []
    for name, raw in files:
        try:
            frames.append(read_one(name, raw))
        except FileProblem as e:
            problems.append(str(e))
    if not frames:
        return pd.DataFrame(columns=["Date", "Description", "Amount", "Bank", "Source file"]), problems, notes
    df = pd.concat(frames, ignore_index=True)
    df["Amount"] = df["Amount"].map(_clean_amount)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    bad = df["Amount"].isna() | df["Date"].isna()
    if bad.any():
        notes.append(f"{int(bad.sum())} row(s) skipped because the date or amount could not be read.")
    df = df[~bad].copy()
    df = df.sort_values("Date").reset_index(drop=True)
    df["Month"] = df["Date"].dt.to_period("M").astype(str)
    return df, problems, notes
