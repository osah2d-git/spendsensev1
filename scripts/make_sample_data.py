"""Generate the made-up (synthetic) bank CSV files used for demos and tests.

Every number here is invented. Several values are "planted" so testers know
the right answer in advance:

Priya (dining spike)
  - Dining Out on the credit card: $437.00 in February, $612.00 in March (+40%)
  - Five subscriptions totalling exactly $87.00 every month
  - One merchant the rules cannot place: "SQ *MOUNTAIN BREW"
  - A $1,250.00 card payment from chequing in March (a transfer, not spending)
  - Payroll deposits of $3,100.00 (money coming in, ignored)

Sam (subscription creep)
  - Eight subscriptions totalling $142.90 a month, dining flat

Run:  python scripts/make_sample_data.py
"""
import csv
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data"
SAMPLE = OUT / "sample"
BAD = OUT / "bad"
MONTHS = [(2026, 1), (2026, 2), (2026, 3)]


def d(y, m, day):
    return f"{y}-{m:02d}-{day:02d}"


def write(path, rows, header=("Date", "Description", "Amount", "Bank"), extra=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(list(header) + ([extra[0]] if extra else []))
        for r in sorted(rows, key=lambda r: r[0]):
            w.writerow(list(r) + ([extra[1]] if extra else []))


def split_total(rng, total, n, lo, hi):
    """n amounts between lo and hi that add up to exactly total."""
    cents = int(round(total * 100))
    for _ in range(10000):
        parts = [rng.randint(int(lo * 100), int(hi * 100)) for _ in range(n - 1)]
        last = cents - sum(parts)
        if lo * 100 <= last <= hi * 100:
            return [p / 100 for p in parts + [last]]
    raise ValueError("cannot split")


def priya():
    rng = random.Random(7)
    chq, visa = [], []
    bank_a, bank_b = "Northern Bank Chequing", "Prairie Visa"
    dining_totals = {1: 455.00, 2: 437.00, 3: 612.00}
    dining_places = ["TIM HORTONS #4412", "STARBUCKS 0391", "A&W RESTAURANT", "EARLS KITCHEN + BAR",
                     "PHO HOA CALGARY", "MCDONALD'S #8821", "SKIP THE DISHES", "UBER EATS"]
    subs = [("NETFLIX.COM", 20.99), ("SPOTIFY P1A2B3", 12.99), ("DISNEY PLUS", 14.99),
            ("CRAVE TV BELL MEDIA", 22.99), ("AUDIBLE CA", 15.04)]  # = 87.00
    for y, m in MONTHS:
        # chequing: income, rent, utilities, phone, transfers
        chq.append((d(y, m, 1), "PAYROLL DEPOSIT ACME ANALYTICS", 3100.00, bank_a))
        chq.append((d(y, m, 15), "PAYROLL DEPOSIT ACME ANALYTICS", 3100.00, bank_a))
        chq.append((d(y, m, 1), "RENT - BELTLINE APTS", -1650.00, bank_a))
        chq.append((d(y, m, 6), "ENMAX ENERGY", -96.40 - m, bank_a))
        chq.append((d(y, m, 9), "TELUS MOBILITY", -75.00, bank_a))
        chq.append((d(y, m, 3), "SAFEWAY #8890", round(-rng.uniform(80, 130), 2), bank_a))
        chq.append((d(y, m, 17), "SAFEWAY #8890", round(-rng.uniform(80, 130), 2), bank_a))
        chq.append((d(y, m, 11), "SUPERSTORE 1577", round(-rng.uniform(60, 110), 2), bank_a))
        chq.append((d(y, m, 21), "CALGARY TRANSIT", -112.00, bank_a))
        chq.append((d(y, m, 24), "PAYMENT - PRAIRIE VISA", -(1250.00 if m == 3 else 1100.00), bank_a))
        chq.append((d(y, m, 27), "SHOPPERS DRUG MART", round(-rng.uniform(15, 45), 2), bank_a))
        # card: dining, subscriptions, shopping, fuel
        for i, (name, amt) in enumerate(subs):
            visa.append((d(y, m, 2 + i), name, -amt, bank_b))
        n_din = {1: 2, 2: 3, 3: 4}[m]
        for i, amt in enumerate(split_total(rng, dining_totals[m], n_din, 40, 260)):
            visa.append((d(y, m, 8 + i * 5), dining_places[(i + m) % len(dining_places)], -amt, bank_b))
    # extra chequing rows to reach 40, extra card rows to reach 25
    chq.append(("2026-03-19", "SQ *MOUNTAIN BREW", -6.75, bank_a))
    chq.append(("2026-02-14", "INDIGO BOOKS 0221", -38.50, bank_a))
    chq.append(("2026-01-28", "PETRO-CANADA 41553", -61.20, bank_a))
    chq.append(("2026-03-28", "PETRO-CANADA 41553", -58.90, bank_a))
    chq.append(("2026-02-26", "SPORT CHEK 312", -89.99, bank_a))
    chq.append(("2026-03-30", "E-TRANSFER RECEIVED J SMITH", 40.00, bank_a))
    chq.append(("2026-01-05", "INTEREST PAID", 0.42, bank_a))
    assert len(chq) == 40, len(chq)
    visa.append(("2026-03-24", "PAYMENT RECEIVED - THANK YOU", 1250.00, bank_b))
    assert len(visa) == 25, len(visa)
    return chq, visa


def sam():
    rng = random.Random(11)
    chq, visa = [], []
    bank_a, bank_b = "Bow Valley Credit Union", "Chinook Mastercard"
    subs = [("NETFLIX.COM", 20.99), ("SPOTIFY P9X8Y7", 12.99), ("DISNEY PLUS", 14.99),
            ("CRAVE TV BELL MEDIA", 22.99), ("APPLE.COM/BILL ICLOUD", 3.99), ("XBOX GAME PASS", 18.99),
            ("PARAMOUNT PLUS", 11.99), ("GOODLIFE FITNESS", 35.97)]  # = 142.90
    for y, m in MONTHS:
        chq.append((d(y, m, 1), "PAYROLL DEPOSIT CITY OF CALGARY", 2750.00, bank_a))
        chq.append((d(y, m, 15), "PAYROLL DEPOSIT CITY OF CALGARY", 2750.00, bank_a))
        chq.append((d(y, m, 1), "RENT PAYMENT - KENSINGTON", -1450.00, bank_a))
        chq.append((d(y, m, 4), "CO-OP GROCERY", round(-rng.uniform(120, 170), 2), bank_a))
        chq.append((d(y, m, 18), "NO FRILLS 3321", round(-rng.uniform(70, 110), 2), bank_a))
        chq.append((d(y, m, 22), "PAYMENT - CHINOOK MASTERCARD", -400.00, bank_a))
        for i, (name, amt) in enumerate(subs):
            visa.append((d(y, m, 3 + i), name, -amt, bank_b))
        for i in range(2):
            visa.append((d(y, m, 12 + i * 9), ["A&W RESTAURANT", "TIM HORTONS #4412"][i], round(-rng.uniform(18, 35), 2), bank_b))
    return chq, visa


def main():
    chq, visa = priya()
    # Bank A also exports an account-number column, which the app must drop.
    write(SAMPLE / "priya_northern_chequing.csv", chq, extra=("Account Number", "0012-3456789"))
    write(SAMPLE / "priya_prairie_visa.csv", visa)
    chq, visa = sam()
    write(SAMPLE / "sam_bowvalley_chequing.csv", chq)
    write(SAMPLE / "sam_chinook_mastercard.csv", visa)
    # bad files for error-handling tests
    BAD.mkdir(parents=True, exist_ok=True)
    write(BAD / "missing_amount.csv", [("2026-03-01", "SAFEWAY", "Northern Bank")], header=("Date", "Description", "Bank"))
    (BAD / "empty.csv").write_text("")
    write(BAD / "odd_amounts.csv", [("2026-03-01", "SAFEWAY", "abc", "Northern Bank"),
                                    ("2026-03-02", "TIM HORTONS", "$4.50-", "Northern Bank"),
                                    ("not a date", "UBER EATS", "-23.10", "Northern Bank"),
                                    ("2026-03-03", "SPOTIFY", "-12.99", "Northern Bank")])
    (BAD / "statement.pdf").write_bytes(b"%PDF-1.4\n% not a real statement\n")
    big = [(d(2026, 1 + i % 3, 1 + i % 28), f"STORE {i % 50}", -round(5 + (i % 97), 2), "Big Bank") for i in range(2000)]
    write(BAD / "large_2000_rows.csv", big)
    print("Sample files written to", OUT)


if __name__ == "__main__":
    main()
