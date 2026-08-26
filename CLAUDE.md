# CLAUDE.md

This file gives Claude Code persistent context for working in this repository. Read this before making changes, and keep it updated as the project evolves.

## Project

Multi-Broker Cross-Account Wash Sale & Tax Loss Harvesting Auditor. A deterministic rules engine that detects wash sales under IRC §1091 across multiple brokerage accounts, computes disallowed losses, and propagates adjusted cost basis, including the Revenue Ruling 2008-5 IRA branch.

Full spec: `wash_sale_auditor_technical_design_v2.md` in the repo root. Treat this as the source of truth for the data model, algorithms, and test matrix. If you're about to implement something that contradicts it, stop and flag the conflict instead of silently picking one interpretation.

**This is a rules engine, not a machine learning project.** Do not introduce ML models, embeddings-as-a-service, or probabilistic classifiers anywhere the design doc specifies deterministic logic or a documented heuristic threshold. The only place approximate matching happens is Tier 3 of the asset equivalence engine (cosine similarity over N-PORT holdings vectors), and even there the thresholds are fixed and documented, not learned.

## Architecture

```
Data Ingestion (Plaid Sandbox / CSV / OFX)
  -> Corporate Action Engine (split normalization)
  -> Asset Equivalence Engine (Tier 1 CUSIP, Tier 2 index lookup, Tier 3 N-PORT similarity)
  -> Wash Sale Detection Engine (61-day chronological matching)
  -> Cost Basis & Tax Ledger Engine (taxable vs. IRA branches)
  -> Reporting Layer (Form 8949 export, Streamlit dashboard)
```

## Build Status

Track phase progress here as you go, update this section at the end of each phase.

- [x] Phase 1: Data layer, ingestion, corporate actions, N-PORT parsing validation
- [x] Phase 2: Equivalence engine, wash sale detection, TC-01 through TC-06 test suite
- [x] Phase 3: Cost basis propagation, Form 8949 export, Streamlit dashboard

Stop at the end of each phase for review before starting the next one, per the build prompt.

## Commands

```bash
# Run the full test suite
pytest -v

# Run only the IRS test matrix cases (TC-01 through TC-06)
pytest -v -k "test_tc"

# Run type checking
mypy src tests

# Run the Streamlit dashboard locally (Phase 3)
streamlit run app/dashboard.py
```

Update these commands as the project structure solidifies, this section should always reflect what actually works right now, not what's planned.

## Coding Conventions

- Type hints on every function signature, no exceptions
- Every `WashSaleEvent` must carry a non-empty, human-readable `rationale` string. A wash sale determination without an explanation is treated as a bug, not a minor omission, explainability is a functional requirement here.
- Where a heuristic is used (Tier 3 similarity thresholds, the chronological matching order in the detection engine), add an inline comment stating explicitly that it's a modeling choice and pointing to the relevant TDD section. Don't present heuristics as settled law anywhere in code or docstrings.
- Use CUSIP as the primary asset identifier wherever available; ticker is a fallback only, tickers get reused and renamed
- Lot-level tracking only, never average-cost basis. Wash sale rules under IRC §1091 apply per-lot, and average cost will silently produce wrong answers on chained wash sales.
- **FIFO Source-Lot Protection**: The detection engine strictly tracks which buy lots were consumed to establish each disposed position, preventing the acquisition of the shares being sold from matching as a replacement purchase for its own sale during 30-day pre-sale lookbacks.
- **Confirmed-Only Basis Propagation**: Cost basis step-up and holding period tacking must strictly operate on confirmed `WashSaleEvent` records where `requires_manual_review` is `False`. Review-band candidates ($0.80 \le \text{score} < 0.95$) are flagged for CPA review and MUST NEVER alter basis or disallow losses automatically.
- **DuckDB Architectural Justification**: DuckDB is utilized specifically for declarative SQL-over-ledger analytics and point-in-time basis queries over the tax lot graph, not as a performance necessity.

## Test Matrix Discipline

Every test case in Section 8 of the TDD (TC-01 through TC-06) must exist as a named pytest test (`test_tc01_...` etc.) before Phase 2 is considered complete. If you add new edge cases beyond the original six, add them to the TDD's Section 8 table too, don't let the test suite and the design doc drift apart.

## Known Open Questions

- **N-PORT parsing library (RESOLVED)**: Arelle returns 0 facts against Form N-PORT-P filings because N-PORT uses its own SEC XML submission schema (`eis_NPORT_Filer.xsd`), not an XBRL instance taxonomy. The lxml-based parser in `src/sec_edgar/nport_parser.py` successfully parses real filings (validated against Vanguard 500 Index Fund, CIK 0000036405, 519 constituent holdings extracted correctly). See `src/sec_edgar/nport_parser.py` for implementation.
- **Form 8949 export format (RESOLVED)**: Standardized on CSV export (`src/reporting/form8949.py`). *Tradeoff analysis*: CSV offers direct, seamless importability into professional tax prep software (TurboTax, TaxAct, Drake) and spreadsheets without external binary rendering dependencies or pagination breakage on large portfolios, while providing exact Form 8949 box columns (1a-1h) and adjustment code 'W'.

## Non-Goals

- Not a tax advice product. The README must state this clearly, and no output (including the Form 8949 export) should be worded in a way that implies IRS-certified accuracy.
- Not trying to be exhaustive on every IRS edge case (e.g., options-for-stock wash sales are explicitly out of scope per Section 4 of the TDD unless we decide to extend later). Don't scope-creep into areas the design doc marked out of scope without flagging it first.