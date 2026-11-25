# Build log

One entry per work session. Record what we asked for, what was built, decisions, tests, problems and the next step.
Prompts and agent interactions here feed the article.

### 21 Nov 2026 | M0, M1 and M2 first version
- Who: David, with Claude (claude.ai)
- Asked for: fill in the build-kit spec from our proposal, then build a first working version
- Built: Streamlit app; CSV loader with checks; merchant rules; Transfers and Money-in handling; totals, chart,
  month-over-month, optional income share and savings rate; saving suggestion calculated in code; Claude for
  unplaced merchants and insights, with a number check and advice filter; made-up sample data with planted answers;
  17 automated tests
- Decisions and why:
  - Income is typed in by the user, not read from deposits: deposits mix pay, refunds and transfers.
  - Card payments and own-account transfers are excluded so spending is not counted twice across banks.
  - Claude never receives transactions or the income amount, only merchant names or totals and percentages.
- Tests a person clicked through and passed: 1, 2, 3, 6, 7, 8, 9, 10 (automated browser run)
- Known problems: insight wording not yet tested with a real API key (tests 4 and 5)
- Next step: add the API key to .env, run tests 4 and 5, then M3 edge cases with real-looking bank exports

### 22 Nov 2026 | Fixes from David's first real test
- Who: David, with Claude (claude.ai)
- Problems found: (1) AI insights always "unavailable"; (2) almost every transaction categorized as "Money in (ignored)"
- Causes: (1) the app hid the real error, so we could not tell whether the key, credit or model was the problem;
  (2) the uploaded credit-card export shows purchases as positive numbers, while SpendSense assumed negative = spending
- Fixes: the AI notice now shows the reason and a Retry button; the loader detects positive-purchase files and flips
  them (with a per-file override), and reads Debit/Credit columns, headerless files and other column names
- Tests: 24 automated checks pass; positive-purchase card file checked in the browser
- Next step: add the API key in Streamlit Secrets, read the reason shown if insights still fail, run tests 4 and 5
