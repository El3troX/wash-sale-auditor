# Multi-Broker Cross-Account Wash Sale & Tax Loss Harvesting Auditor

> ⚠️ **IMPORTANT DISCLAIMER**  
> **This project is strictly an educational and portfolio research demonstration. It does NOT provide certified legal, financial, or tax advice, and has NOT been audited or certified by a CPA or tax attorney.** Wash sale rules under IRC §1091 and associated rulings involve complex facts-and-circumstances determinations. Never submit tax filings or claim deductions based solely on software outputs without consulting a licensed CPA or tax professional.

---

## Overview

The **Multi-Broker Cross-Account Wash Sale & Tax Loss Harvesting Auditor** is a deterministic rules engine with a temporal graph-matching core designed to solve a fundamental blindspot in modern retail tax loss harvesting: **cross-broker wash sales**.

Under **IRC §1091**, a wash sale occurs when a taxpayer sells stock or securities at a loss and, within a 61-day window ($[-30\text{ days}, +30\text{ days}]$), acquires substantially identical stock or securities. Individual brokerage firms (Fidelity, Schwab, Robinhood, etc.) calculate wash sales **only within their own siloed accounts**. When an investor executes trades across multiple accounts (e.g. taxable brokerage, robo-advisors, and Roth IRAs), siloed 1099-B reports miss cross-account replacement purchases.

This project ingests multi-broker transaction streams, normalizes corporate actions (stock splits), executes a 3-tier asset equivalence engine, runs a 61-day sliding-window chronological matching algorithm, propagates lot-level cost basis and holding periods, correctly handles the **Revenue Ruling 2008-5** IRA permanent disallowance branch, and exports IRS **Form 8949** audit records.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       Data Ingestion                        │
│  - Plaid Sandbox API Payload Normalization                 │
│  - Broker CSV Exports (Fidelity, Schwab, Generic)           │
│  - OFX / QFX Parsing (SGML 1.x & XML 2.x)                  │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  Corporate Action Engine                    │
│  - Mandatory Split Adjustment (Forward & Reverse)           │
│  - Online Split History (Yahoo Finance API)                │
│  - Explicit Audit Warnings on Unverified Tickers            │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Asset Equivalence Engine                    │
│  - Tier 1: Exact CUSIP Match & Ticker Fallback              │
│  - Tier 2: Curated ETF-to-Benchmark Index Lookup            │
│  - Tier 3: Sparse N-PORT Cosine Similarity Engine           │
│    ├── Score >= 0.95  : Confirmed Substantially Identical   │
│    └── 0.80 <= Score < 0.95 : Flagged Review Candidate     │
│        (NO Auto-Disallowance without CPA Review)            │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Wash Sale Detection Engine                  │
│  - 61-Day Temporal Sliding Window ([-30d, +30d])            │
│  - FIFO Source-Lot Protection (Excludes Disposed Buys)      │
│  - Chronological Priority for Competing Loss Sales          │
│  - Same-Day Duplicate Execution Leg Exclusion               │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│              Cost Basis & Tax Ledger Engine                 │
│  - Taxable Accounts: Basis Step-Up + Holding Period Tacking │
│  - IRA Accounts (Rev. Rul. 2008-5): $0 Basis Adjustment     │
│  - Chained Wash Sale Compounded Basis Propagation           │
│  - DuckDB Relational SQL-over-Ledger Analytics Engine       │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      Reporting Layer                        │
│  - IRS Form 8949 CSV Exporter (Adjustment Code 'W')         │
│  - Interactive Streamlit Dashboard with Plotly Timelines    │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Design Principles & Safeguards

1. **Deterministic Rules Core**: Built on deterministic graph matching and exact lot-level accounting, avoiding opaque ML models where legal and tax specifications require explicit auditability.
2. **Tier 3 Review Band Safeguard ($0.80 \le \text{Score} < 0.95$)**: Correlated ETFs in the mid-band are routed to a manual review queue with `disallowed_loss = 0.0`. They are never auto-disallowed and never consume replacement lot quantities without CPA confirmation.
3. **FIFO Source-Lot Protection**: When a position is sold, the engine tracks which earlier buy lot established that position and excludes it from matching as a replacement purchase for its own disposition, while preserving legitimate pre-sale replacement buys (e.g. TC-02).
4. **Revenue Ruling 2008-5 Permanent Disallowance**: When replacement shares are acquired inside an IRA, the loss on the taxable sale is permanently disallowed, the IRA replacement lot receives **$0 basis step-up**, and holding period days are not tacked.
5. **DuckDB SQL-over-Ledger**: DuckDB is utilized for analytical SQL queries (point-in-time open lots, cross-broker tax aggregations, Form 8949 dispositions), providing a declarative interface over the tax lot graph.
6. **Form 8949 CSV Exporter**: Formatted to the IRS Form 8949 specification (`1a_description` through `1h_gain_loss` with adjustment code `W`), enabling direct upload to tax preparation software (TurboTax, TaxAct, Drake) and spreadsheets.

---

## IRS Test Matrix (Section 8 Verification)

| Test ID | Scenario Description | Expected Outcome | Status |
| :--- | :--- | :--- | :--- |
| **TC-01** | IRS Pub 550 Single-Account Baseline | 100 shs AAPL sold at loss, repurchased in 14d &rarr; $2,000 disallowed, basis $110/sh | `PASSED` |
| **TC-02** | 30-Day Lookback Pre-Sale Acquisition | Buy replacement 14d *before* loss sale &rarr; $2,000 disallowed loss | `PASSED` |
| **TC-03** | Cross-Broker ETF Swap | Sell VOO (Fidelity), buy IVV (Schwab) in 5d &rarr; Tier 2 wash sale, $3,000 disallowed | `PASSED` |
| **TC-04** | IRA Repurchase (Rev. Rul. 2008-5) | Sell SPY (Taxable), buy SPY (Roth IRA) &rarr; $4,000 permanent disallowance, $0 basis relief | `PASSED` |
| **TC-05a**| Chained Wash Sales | Replacement lot sold at loss &rarr; Disallowed loss compounds across basis ($120 &rarr; $125 &rarr; $128/sh) | `PASSED` |
| **TC-05b**| Competing Loss Sales | S1 and S2 compete for B1 &rarr; Earlier S1 claims shares first; S2 remains deductible | `PASSED` |
| **TC-06** | Same-Day Duplicate Leg Exclusion | Same-day duplicate broker transaction ID excluded &rarr; 0 wash sales | `PASSED` |

---

## Local Setup & Quickstart

### Prerequisites
- Python 3.11 or higher
- `pip` or virtual environment manager

### Installation
```bash
# 1. Clone or navigate to the project directory
cd "FinTech Project"

# 2. Create and activate a virtual environment
python -m venv .venv
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# On macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

### Running Tests & Type Checking
```bash
# Run the full test suite (50 tests)
pytest -v

# Run the IRS test matrix scenarios (TC-01 through TC-06)
pytest -v -k "test_tc"

# Run static type checking
mypy src tests
```

### Running the Streamlit Dashboard
```bash
streamlit run app/dashboard.py
```
Open `http://localhost:8501` in your browser to inspect the interactive timeline, lot-level ledger, confirmed vs. review candidate audit trails, and Form 8949 CSV exporter.

---

## Project Structure

```
├── app/
│   └── dashboard.py               # Streamlit interactive UI with Plotly timelines
├── data/
│   ├── sample_fidelity.csv        # Sample Fidelity CSV export
│   ├── sample_schwab.csv          # Sample Schwab CSV export
│   ├── sample_vanguard.ofx        # Sample Vanguard OFX export
│   └── sample_nport_raw.xml       # Real Vanguard 500 SEC Form N-PORT XML filing
├── src/
│   ├── models/
│   │   ├── entities.py            # Account, Transaction, TaxLot, WashSaleEvent, AssetProfile
│   │   └── enums.py               # AccountType, TransactionType
│   ├── ingestion/
│   │   ├── csv_parser.py          # Multi-broker CSV ingestion engine
│   │   ├── ofx_parser.py          # SGML 1.x & XML 2.x OFX/QFX parser
│   │   ├── plaid_client.py        # Plaid investment transactions normalizer
│   │   └── pipeline.py            # Unified ingestion pipeline with mandatory split adjustments
│   ├── corporate_actions/
│   │   └── split_adjuster.py      # Stock split normalizer & Yahoo Finance API integration
│   ├── sec_edgar/
│   │   └── nport_parser.py        # SEC XML Form N-PORT parser
│   ├── equivalence/
│   │   ├── data/
│   │   │   └── etf_index_mappings.json # Extensible benchmark index tracking ETF database
│   │   ├── tier1.py               # CUSIP & Ticker exact matcher
│   │   ├── tier2.py               # Index-tracking lookup matcher
│   │   ├── tier3.py               # Sparse N-PORT constituent cosine similarity matcher
│   │   └── engine.py              # 3-Tier Equivalence Engine
│   ├── detection/
│   │   └── wash_sale_engine.py    # 61-day sliding window graph-matching engine
│   ├── ledger/
│   │   ├── cost_basis.py          # Lot-level basis step-up & holding period tacking engine
│   │   └── duckdb_ledger.py       # DuckDB SQL-over-ledger analytics database
│   └── reporting/
│       └── form8949.py            # IRS Form 8949 standard CSV exporter
├── tests/
│   ├── conftest.py                # Multi-account fixtures (TC-01 through TC-06 & Composite)
│   ├── test_corporate_actions.py  # Split adjustment tests
│   ├── test_csv_parser.py         # CSV parser unit tests
│   ├── test_ofx_parser.py         # OFX multi-broker parser tests
│   ├── test_plaid_client.py       # Plaid normalization tests
│   ├── test_nport_parser.py       # N-PORT XML parser tests
│   ├── test_equivalence.py        # 3-Tier equivalence & N-PORT integration tests
│   ├── test_wash_sale_engine.py   # TC-01 to TC-06 wash sale detection tests
│   ├── test_ledger.py             # Basis step-up, IRA disallowance, & DuckDB queries
│   └── test_end_to_end_pipeline.py# Full pipeline end-to-end integration test
├── CLAUDE.md                      # Architecture, commands, conventions, and status
├── TDD.md                         # Technical Design Document
├── pyproject.toml                 # Build configuration & mypy settings
└── requirements.txt               # Pinned dependencies
```
