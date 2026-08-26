# Multi-Broker Cross-Account Wash Sale & Tax Loss Harvesting Auditor
## Production Technical Design Document (TDD) v2

---

## 1. System Overview

The Multi-Broker Wash Sale Auditor ingests multi-account transaction ledgers, detects cross-brokerage wash sales under Internal Revenue Code (IRC) §1091, calculates disallowed capital losses, and dynamically adjusts cost basis across taxable and tax-advantaged accounts.

**Core Insight**: Cross-account wash sale detection is a temporal graph matching problem over a sliding 61-day window. Each loss-realization transaction opens a window of 30 days prior to and 30 days after the trade date. Matching replacement acquisitions across disparate brokerages requires:

- Deterministic and heuristic asset equivalence mapping
- Temporal sliding-window matching with lot-level allocation
- Basis propagation rules parameterized by account tax status (taxable vs. IRA)

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                 Data Ingestion Layer                     │
│   (Plaid API Sandbox / OFX Files / Broker CSV Exports)   │
└────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│               Corporate Action Engine                    │
│   (Split Adjustment & Stock Dividend Re-normalization)   │
└────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│               Asset Equivalence Engine                   │
│  - Tier 1: CUSIP / Ticker Exact Match                     │
│  - Tier 2: Index Tracking Equivalence Lookup              │
│  - Tier 3: Sparse N-PORT Cosine Similarity Engine         │
└────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│             Wash Sale Detection Engine                   │
│    (61-Day Chronological Event Stream Matching)           │
└────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│            Cost Basis & Tax Ledger Engine                │
│  - Taxable Accounts: Basis Adjustment & Holding Tacking   │
│  - Tax-Advantaged (IRA): Revenue Ruling 2008-5 Branch     │
└────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│             Reporting & Attribution Layer                │
│       (Form 8949 Audit Trail & Rule Explanations)         │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Data Model & Schema Definitions

### 3.1 Core Entity Schemas

```python
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Dict, Optional

class AccountType(Enum):
    TAXABLE = "taxable"
    ROTH_IRA = "roth_ira"
    TRADITIONAL_IRA = "traditional_ira"
    ROBO_MANAGED = "robo_managed"

class TransactionType(Enum):
    BUY = "buy"
    SELL = "sell"

@dataclass
class Account:
    account_id: str
    broker_name: str
    account_type: AccountType

@dataclass
class Transaction:
    transaction_id: str
    account_id: str
    ticker: str
    cusip: Optional[str]
    transaction_type: TransactionType
    quantity: float
    price_per_share: float
    trade_date: date
    settlement_date: date
    realized_gain_loss: Optional[float] = None
    unmatched_quantity: float = 0.0

@dataclass
class AssetProfile:
    ticker: str
    cusip: Optional[str]
    asset_type: str  # equity, etf, mutual_fund
    holdings_vector: Dict[str, float]  # constituent_ticker -> weight
    tracked_index: Optional[str] = None
    last_updated: Optional[date] = None

@dataclass
class WashSaleEvent:
    event_id: str
    loss_transaction_id: str
    replacement_transaction_id: str
    matched_quantity: float
    disallowed_loss: float
    similarity_score: float
    window_days: int
    is_ira_disallowance: bool
    rationale: str
```

### 3.2 Identification Strategy: CUSIP & Ticker Disambiguation

Tickers undergo corporate renames (e.g., FB → META) and exchange changes. The pipeline enforces a fallback taxonomy:

- **Primary Identifier**: Standard 9-character CUSIP retrieved via Plaid or EDGAR.
- **Secondary Fallback**: Exchange-qualified ticker symbol (e.g., NASDAQ:AAPL).
- **Corporate Action Adjustment**: Transactions are normalized by cumulative split ratios S(t) prior to evaluation:

Q_adj = Q_raw × S(t), P_adj = P_raw / S(t)

---

## 4. Asset Equivalence Engine

Under IRC §1091, wash sales apply to "substantially identical" stocks or securities. The system evaluates equivalence through a 3-tier deterministic-to-statistical hierarchy.

```
Is CUSIP identical?
    YES → TIER 1: MATCH
    NO  → Do funds track identical indices?
              YES → TIER 2: MATCH
              NO  → Is Holdings Cosine Similarity ≥ 0.95?
                        YES → TIER 3: MATCH
                        NO  → NO MATCH / AUDIT (0.80-0.95 flagged for review)
```

### 4.1 Tier 1: Exact Identifier Match

If CUSIP_A = CUSIP_B, the securities are identical.

### 4.2 Tier 2: Index Tracking Equivalence

For index ETFs, direct CUSIP matching fails (e.g., Vanguard VOO vs. iShares IVV). The system maintains a curated lookup table mapping fund tickers to target benchmark indices. This table is a finite, slowly-changing list (a few hundred major ETFs), curate it manually from fund prospectuses rather than trying to infer it.

### 4.3 Tier 3: Portfolio Constituent Cosine Similarity

For unmapped funds, SEC Form N-PORT quarterly disclosures are parsed to extract portfolio holdings weights. Equivalence score is computed via sparse cosine similarity between holdings vectors.

**Decision thresholds:**
- Similarity ≥ 0.95: Automatic wash sale flag
- 0.80 ≤ Similarity < 0.95: Flagged for user compliance review with visual holdings overlap breakdown, never auto-disallowed
- Similarity < 0.80: Distinct assets, no wash sale

**Important implementation note on N-PORT parsing**: Confirm your parsing library actually handles Form N-PORT before architecting around it. N-PORT-P filings use their own XML schema, they are not standard XBRL, so a general-purpose XBRL processor may not parse them cleanly out of the box. Validate against one real filing in your first day of Week 1. If the general-purpose parser doesn't work, fall back to a direct lxml parser against the published N-PORT XSD, this is a fine and common approach, just budget the extra day for it rather than discovering the gap mid-Week-2.

---

## 5. Wash Sale Detection Engine

### 5.1 Temporal Window Definition

Let S_i be a sell transaction on date t(S_i) producing a realized loss L_i > 0. The wash sale window is the closed interval:

W(S_i) = [t(S_i) − 30 days, t(S_i) + 30 days]

A buy transaction B_j on date t(B_j) in any linked account triggers a wash sale if t(B_j) is in W(S_i) AND the two securities are equivalent.

### 5.2 Matching Order Is a Deliberate Design Choice

When multiple loss sales compete for the same limited pool of replacement shares, this engine processes loss sales in chronological order and greedily consumes available replacement quantity as it iterates. This means: if two separate loss sales on different dates could each claim the same replacement buy, the earlier-dated loss sale wins the match first, and the later sale only matches whatever replacement quantity remains.

This is a defensible interpretation (it mirrors how a taxpayer reasoning sequentially through their own trade history would apply the rule), but it is a choice, not a mathematical certainty, document it explicitly in your README and cover it with an explicit test case (TC-05 below) so it reads as intentional design rather than an artifact of implementation order.

### 5.3 Chronological Matching Algorithm

```python
def detect_wash_sales(transactions: list[Transaction], equivalence_engine) -> list[WashSaleEvent]:
    sorted_txs = sorted(transactions, key=lambda x: x.trade_date)
    wash_events = []

    loss_sells = [
        tx for tx in sorted_txs
        if tx.transaction_type == TransactionType.SELL and tx.realized_gain_loss and tx.realized_gain_loss < 0
    ]

    for sell in loss_sells:
        sell.unmatched_quantity = sell.quantity
        window_start = sell.trade_date - timedelta(days=30)
        window_end = sell.trade_date + timedelta(days=30)

        candidates = [
            tx for tx in sorted_txs
            if tx.transaction_type == TransactionType.BUY
            and window_start <= tx.trade_date <= window_end
            and tx.unmatched_quantity > 0
            and not (tx.transaction_id == sell.transaction_id)  # exclude same lot, same-day edge case
            and equivalence_engine.are_equivalent(sell.ticker, tx.ticker)
        ]

        for buy in candidates:
            if sell.unmatched_quantity <= 0:
                break

            match_qty = min(sell.unmatched_quantity, buy.unmatched_quantity)
            unit_loss = abs(sell.realized_gain_loss) / sell.quantity
            disallowed = match_qty * unit_loss

            target_account = get_account(buy.account_id)
            is_ira = target_account.account_type in (AccountType.ROTH_IRA, AccountType.TRADITIONAL_IRA)

            wash_events.append(WashSaleEvent(
                event_id=f"WS-{sell.transaction_id}-{buy.transaction_id}",
                loss_transaction_id=sell.transaction_id,
                replacement_transaction_id=buy.transaction_id,
                matched_quantity=match_qty,
                disallowed_loss=disallowed,
                similarity_score=equivalence_engine.get_score(sell.ticker, buy.ticker),
                window_days=abs((buy.trade_date - sell.trade_date).days),
                is_ira_disallowance=is_ira,
                rationale=f"Loss sale of {sell.ticker} matched with purchase of {buy.ticker} across {target_account.broker_name}"
            ))

            sell.unmatched_quantity -= match_qty
            buy.unmatched_quantity -= match_qty

    return wash_events
```

### 5.4 FIFO Source-Lot Protection Mechanism

Under IRC §1091, the acquisition that established the shares being sold cannot be treated as a replacement purchase for its own disposition. To prevent false-positive self-matching during the 30-day lookback window while correctly capturing separate pre-sale replacement acquisitions (e.g. TC-02), the detection engine maintains a FIFO open-lot inventory map (`_map_disposed_lots`). When a sell occurs, it identifies the specific historical buy transactions consumed to establish the sold position (`source_buy_ids`) and explicitly excludes those buy transaction IDs from the candidate replacement pool for that specific sell. This source-lot mapping is also preserved for holding-period tacking in Phase 3.

---

## 6. Cost Basis & Tax Propagation Engine

### 6.1 Taxable Account Path

For replacement purchases in taxable accounts, the disallowed loss is added to the cost basis of the acquired replacement lot, and the holding period of the original position tacks onto the replacement:

Basis_adj = Cost_original + Loss_disallowed

Holding_period_adj = Holding_period(original) + Holding_period(replacement)

### 6.2 Tax-Advantaged Account Path (IRS Revenue Ruling 2008-5)

If the replacement buy occurs within an IRA (Roth or Traditional):

- The loss remains **permanently** disallowed
- Loss_disallowed **cannot** be added to the cost basis of the IRA asset
- The tax deduction is permanently lost, preventing taxpayers from converting taxable losses into non-taxable IRA positions

```python
def apply_cost_basis_adjustment(buy_tx: Transaction, wash_event: WashSaleEvent, account: Account):
    if account.account_type in (AccountType.ROTH_IRA, AccountType.TRADITIONAL_IRA):
        # Revenue Ruling 2008-5: permanent disallowance, no basis relief
        buy_tx.adjusted_basis = buy_tx.price_per_share * buy_tx.quantity
        wash_event.rationale += " [PERMANENT DISALLOWANCE: Replacement purchased in IRA under Rev. Rul. 2008-5]"
    else:
        # Standard IRC §1091: basis increases by disallowed loss
        buy_tx.adjusted_basis = (buy_tx.price_per_share * buy_tx.quantity) + wash_event.disallowed_loss
```

---

## 7. Technology Stack

- **Core Processing**: Python 3.11+, pandas for tabular structures, numpy for vectorized window calculations
- **Graph & Similarity Analytics**: scikit-learn (sparse cosine similarity), networkx (transaction lineage graph)
- **Data Persistence**: DuckDB. Justify this explicitly in your writeup rather than presenting it as a performance necessity, at the transaction volumes a solo project will realistically handle, pandas alone is sufficient. Use DuckDB specifically to demonstrate SQL-over-ledger querying for the reporting layer (e.g., point-in-time basis lookups via `SELECT` rather than pandas filtering), that's a real skill signal, "performance" is not, since this dataset will never be large enough to need it
- **External Data Connectors**: plaid-python (Plaid Sandbox API); N-PORT parser (validate Arelle first, fall back to a custom lxml parser against the N-PORT XSD if needed, see Section 4.3)
- **User Interface**: Streamlit dashboard with an interactive trade timeline (Plotly)

---

## 8. Verification Strategy & Test Matrix

| Test Case | Description | Expected Result |
|---|---|---|
| TC-01 | IRS Pub 550 baseline: buy 100 shares, sell at loss, rebuy within 20 days, single account | 100% loss disallowed; basis increased on replacement lot |
| TC-02 | 30-day lookback: buy replacement 15 days *before* selling original at a loss | Wash sale triggered (pre-sale window capture) |
| TC-03 | Cross-broker ETF swap: sell VOO at a loss in Fidelity, buy IVV in Schwab within 5 days | Tier 2 match, cross-account loss disallowed |
| TC-04 | IRA Revenue Ruling 2008-5: sell SPY at a loss in taxable account, buy SPY in Roth IRA 10 days later | Loss permanently disallowed, $0 basis adjustment to IRA |
| TC-05 | Chained wash sales: replacement lot B1 is later sold at a loss, triggering a wash sale with B2; also two loss sales compete for one replacement buy | Sequential basis propagation B1 → B2; earlier-dated loss sale claims replacement quantity first, confirming matching order is intentional |
| TC-06 | Same-day same-lot edge case: a sell transaction should never match against itself or a same-day buy in the exact same lot reported as two legs by a broker | No false-positive wash sale generated from the sell transaction's own settlement leg |

---

## 9. Implementation Roadmap

**Phase 1 (Week 1): Pipeline Ingestion & Schema Foundations**
- Implement Plaid Sandbox and CSV/OFX parser connectors
- Build corporate action normalization engine for splits
- Validate N-PORT parsing approach against one real filing on Day 1, before committing to Arelle vs. custom lxml parsing for the rest of the week

**Phase 2 (Week 2): Equivalence & Sliding Window Core Engine**
- Implement Tier 1-3 asset equivalence engine
- Implement 61-day chronological matching algorithm
- Write the full TC-01 through TC-06 test suite alongside the engine, not after

**Phase 3 (Week 3): Tax Ledger, Revenue Ruling 2008-5 & UI**
- Implement taxable vs. IRA basis propagation logic
- Deploy Streamlit visual ledger and Form 8949-style reporting exporter
- Buffer 2-3 days for N-PORT parsing overruns if Phase 1's validation step surfaced issues

---

## 10. Framing for Portfolio

Position this as a **deterministic financial rules engine with graph-based temporal correlation and multi-jurisdiction tax logic** (taxable vs. IRA branches), not as a machine learning project. The technical depth is in correctly modeling IRC §1091 and Revenue Ruling 2008-5 as code, handling the cross-account temporal graph with lot-level precision, and being explicit about where heuristics (Tier 3 similarity) diverge from settled law rather than presenting them as definitive.