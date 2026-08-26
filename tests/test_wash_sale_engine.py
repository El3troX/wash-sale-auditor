"""
Pytest Test Suite for Wash Sale Detection Engine.
Strictly implements and verifies the complete test matrix defined in Section 8 of the TDD (TC-01 through TC-06),
along with additional Tier 2 ETF swaps, Tier 3 review-band safeguards, and composite multi-account reconciliation.
"""

from datetime import date
from typing import Dict, List
import pytest

from src.detection.wash_sale_engine import WashSaleDetectionEngine
from src.equivalence.engine import EquivalenceEngine
from src.models.entities import Account, AssetProfile, Transaction, WashSaleEvent
from src.models.enums import AccountType, TransactionType


@pytest.fixture
def detection_engine() -> WashSaleDetectionEngine:
    return WashSaleDetectionEngine()


def test_tc01_irs_pub_550_baseline(
    detection_engine: WashSaleDetectionEngine,
    multi_accounts: Dict[str, Account],
    tc01_dataset: List[Transaction],
) -> None:
    """
    TC-01: IRS Pub 550 Baseline
    Single taxable account: Buy 100 shares @ $100, sell @ $80 (loss $2,000), rebuy 100 @ $90 within 14 days.
    Expected: 100% loss ($2,000.00) disallowed.
    """
    events = detection_engine.detect_wash_sales(tc01_dataset, multi_accounts)

    assert len(events) == 1
    ev = events[0]
    assert ev.loss_transaction_id == "TC01-SELL-1"
    assert ev.replacement_transaction_id == "TC01-BUY-2"
    assert ev.matched_quantity == 100.0
    assert ev.disallowed_loss == 2000.0
    assert ev.window_days == 14
    assert not ev.is_ira_disallowance
    assert not ev.requires_manual_review
    assert "Wash sale under IRC §1091" in ev.rationale


def test_tc02_lookback_window(
    detection_engine: WashSaleDetectionEngine,
    multi_accounts: Dict[str, Account],
    tc02_dataset: List[Transaction],
) -> None:
    """
    TC-02: 30-Day Lookback Window
    Buy replacement 14 days BEFORE selling original lot at a loss.
    Expected: Wash sale triggered via pre-sale 30-day window capture.
    """
    events = detection_engine.detect_wash_sales(tc02_dataset, multi_accounts)

    assert len(events) == 1
    ev = events[0]
    assert ev.loss_transaction_id == "TC02-SELL-LOSS"
    assert ev.replacement_transaction_id == "TC02-BUY-REPL"
    assert ev.matched_quantity == 50.0
    assert ev.disallowed_loss == 2000.0
    assert ev.window_days == 14
    assert "14 days before sell" in ev.rationale


def test_tc03_cross_broker_etf_swap(
    detection_engine: WashSaleDetectionEngine,
    multi_accounts: Dict[str, Account],
    tc03_dataset: List[Transaction],
) -> None:
    """
    TC-03: Cross-Broker ETF Swap
    Sell VOO at loss in Fidelity Taxable, buy IVV in Charles Schwab Taxable 5 days later.
    Expected: Tier 2 equivalence match (S&P 500 benchmark), $3,000 cross-account loss disallowed.
    """
    events = detection_engine.detect_wash_sales(tc03_dataset, multi_accounts)

    assert len(events) == 1
    ev = events[0]
    assert ev.loss_transaction_id == "TC03-SELL-VOO"
    assert ev.replacement_transaction_id == "TC03-BUY-IVV"
    assert ev.matched_quantity == 100.0
    assert ev.disallowed_loss == 3000.0
    assert ev.tier == 2
    assert "Tier 2 Index Tracking Equivalence" in ev.rationale
    assert "Fidelity" in ev.rationale and "Charles Schwab" in ev.rationale


def test_tc03_additional_qqq_qqqm_swap(
    detection_engine: WashSaleDetectionEngine,
    multi_accounts: Dict[str, Account],
) -> None:
    """
    Additional Tier 2 Test: QQQ (sold at loss in Wealthfront Robo) -> QQQM (bought in Fidelity Taxable).
    Validates Nasdaq-100 benchmark index equivalence across distinct accounts.
    """
    wf = multi_accounts["wealthfront_robo"]
    fid = multi_accounts["fidelity_taxable"]

    txs = [
        Transaction(
            transaction_id="TX-SELL-QQQ",
            account_id=wf.account_id,
            ticker="QQQ",
            cusip=None,
            transaction_type=TransactionType.SELL,
            quantity=50.0,
            price_per_share=420.0,
            trade_date=date(2024, 6, 1),
            settlement_date=date(2024, 6, 3),
            realized_gain_loss=-1500.0,
        ),
        Transaction(
            transaction_id="TX-BUY-QQQM",
            account_id=fid.account_id,
            ticker="QQQM",
            cusip=None,
            transaction_type=TransactionType.BUY,
            quantity=50.0,
            price_per_share=175.0,
            trade_date=date(2024, 6, 10),
            settlement_date=date(2024, 6, 12),
        ),
    ]

    events = detection_engine.detect_wash_sales(txs, multi_accounts)

    assert len(events) == 1
    ev = events[0]
    assert ev.loss_transaction_id == "TX-SELL-QQQ"
    assert ev.replacement_transaction_id == "TX-BUY-QQQM"
    assert ev.disallowed_loss == 1500.0
    assert ev.tier == 2
    assert "Nasdaq-100" in ev.rationale


def test_tc04_ira_revenue_ruling_2008_5(
    detection_engine: WashSaleDetectionEngine,
    multi_accounts: Dict[str, Account],
    tc04_dataset: List[Transaction],
) -> None:
    """
    TC-04: IRA Revenue Ruling 2008-5
    Sell SPY at loss in Fidelity Taxable, buy SPY in Vanguard Roth IRA 10 days later.
    Expected: Loss permanently disallowed, is_ira_disallowance = True.
    """
    events = detection_engine.detect_wash_sales(tc04_dataset, multi_accounts)

    assert len(events) == 1
    ev = events[0]
    assert ev.loss_transaction_id == "TC04-SELL-TAXABLE"
    assert ev.replacement_transaction_id == "TC04-BUY-ROTH"
    assert ev.matched_quantity == 100.0
    assert ev.disallowed_loss == 4000.0
    assert ev.is_ira_disallowance
    assert "Rev. Rul. 2008-5" in ev.rationale
    assert "PERMANENT DISALLOWANCE" in ev.rationale


def test_tc05a_chained_wash_sales(
    detection_engine: WashSaleDetectionEngine,
    multi_accounts: Dict[str, Account],
    tc05_chained_dataset: List[Transaction],
) -> None:
    """
    TC-05 Sub-case A: Chained Wash Sales
    Buy B0 -> Sell S0 at loss -> Rebuy B1 (wash sale 1) -> Sell S1 at loss -> Rebuy B2 (wash sale 2).
    Expected: Two sequential wash sale events detected (S0 -> B1, and S1 -> B2).
    """
    events = detection_engine.detect_wash_sales(tc05_chained_dataset, multi_accounts)

    assert len(events) == 2

    # First wash sale: S0 ($1000 loss) matched to B1
    ev1 = events[0]
    assert ev1.loss_transaction_id == "TC05-SELL-S0"
    assert ev1.replacement_transaction_id == "TC05-BUY-B1"
    assert ev1.disallowed_loss == 1000.0

    # Second wash sale: S1 ($500 loss) matched to B2
    ev2 = events[1]
    assert ev2.loss_transaction_id == "TC05-SELL-S1"
    assert ev2.replacement_transaction_id == "TC05-BUY-B2"
    assert ev2.disallowed_loss == 500.0


def test_tc05b_competing_loss_sales_chronological_order(
    detection_engine: WashSaleDetectionEngine,
    multi_accounts: Dict[str, Account],
    tc05_competing_dataset: List[Transaction],
) -> None:
    """
    TC-05 Sub-case B: Two Loss Sales Competing for One Replacement Buy
    Loss Sell S1 (Aug 1, qty 50) and Loss Sell S2 (Aug 10, qty 50) competing for Buy B1 (Aug 15, qty 50).
    Expected: S1 claims the 50 replacement shares first due to strict chronological ordering (Section 5.2).
    S2 receives 0 matched shares, and exactly 1 wash sale event is created.
    """
    events = detection_engine.detect_wash_sales(tc05_competing_dataset, multi_accounts)

    assert len(events) == 1
    ev = events[0]
    # S1 must win the match
    assert ev.loss_transaction_id == "TC05B-SELL-S1"
    assert ev.replacement_transaction_id == "TC05B-BUY-B1"
    assert ev.matched_quantity == 50.0
    assert ev.disallowed_loss == 1500.0

    # Verify S2 was left unmatched and fully deductible
    s2_tx = next(t for t in tc05_competing_dataset if t.transaction_id == "TC05B-SELL-S2")
    assert s2_tx.unmatched_quantity == 50.0


def test_tc06_same_day_same_lot_exclusion(
    detection_engine: WashSaleDetectionEngine,
    multi_accounts: Dict[str, Account],
    tc06_dataset: List[Transaction],
) -> None:
    """
    TC-06: Same-Day Same-Lot False Positive Prevention
    A sell transaction should not match against its own duplicate transaction ID leg reported on the same day.
    """
    events = detection_engine.detect_wash_sales(tc06_dataset, multi_accounts)
    # The duplicate leg TC06-SELL-SAME-LOT is excluded by transaction_id filter
    # TC06-ORIG-BUY occurred on the same day (acquisition of the position being sold),
    # which is not a replacement acquisition under §1091.
    assert len(events) == 0


def test_tier3_review_band_does_not_auto_disallow(
    multi_accounts: Dict[str, Account],
) -> None:
    """
    Safeguard Test for Tier 3:
    Funds with cosine similarity in the review band [0.80, 0.95) must be flagged with
    requires_manual_review = True and disallowed_loss = 0.0 (NO automatic disallowance).
    """
    engine = EquivalenceEngine()
    # Register profiles in the review band (score ~ 0.88)
    p1 = AssetProfile(
        ticker="SECTOR_A",
        asset_type="etf",
        holdings_vector={"NVDA": 0.50, "AMD": 0.30, "INTC": 0.20},
        last_updated=date(2024, 1, 1),
    )
    p2 = AssetProfile(
        ticker="SECTOR_B",
        asset_type="etf",
        holdings_vector={"NVDA": 0.50, "AMD": 0.50},
        last_updated=date(2024, 1, 1),
    )
    engine.register_asset_profile(p1)
    engine.register_asset_profile(p2)

    detector = WashSaleDetectionEngine(equivalence_engine=engine)
    fid = multi_accounts["fidelity_taxable"]

    txs = [
        Transaction(
            transaction_id="TX-SELL-SEC-A",
            account_id=fid.account_id,
            ticker="SECTOR_A",
            cusip=None,
            transaction_type=TransactionType.SELL,
            quantity=100.0,
            price_per_share=50.0,
            trade_date=date(2024, 7, 1),
            settlement_date=date(2024, 7, 3),
            realized_gain_loss=-1000.0,
        ),
        Transaction(
            transaction_id="TX-BUY-SEC-B",
            account_id=fid.account_id,
            ticker="SECTOR_B",
            cusip=None,
            transaction_type=TransactionType.BUY,
            quantity=100.0,
            price_per_share=52.0,
            trade_date=date(2024, 7, 10),
            settlement_date=date(2024, 7, 12),
        ),
    ]

    events = detector.detect_wash_sales(txs, multi_accounts)

    assert len(events) == 1
    ev = events[0]
    assert ev.requires_manual_review
    assert ev.disallowed_loss == 0.0  # MUST be 0.0 (no auto-disallowance)
    assert 0.80 <= ev.similarity_score < 0.95
    assert "MANUAL CPA REVIEW REQUIRED" in ev.rationale


def test_full_composite_portfolio_reconciliation(
    detection_engine: WashSaleDetectionEngine,
    multi_accounts: Dict[str, Account],
    full_portfolio_dataset: List[Transaction],
) -> None:
    """
    Comprehensive End-to-End Reconciliation over full multi-account tax-year ledger.
    Asserts exact total disallowed losses, exact event counts, and IRA tag accuracy across all scenarios.
    """
    events = detection_engine.detect_wash_sales(full_portfolio_dataset, multi_accounts)

    # Expected events:
    # TC-01: $2,000.00
    # TC-02: $2,000.00
    # TC-03: $3,000.00
    # TC-04: $4,000.00 (IRA permanent disallowance)
    # TC-05a: $1,000.00 + $500.00 = $1,500.00
    # TC-05b: $1,500.00 (S1 wins, S2 zero)
    # TC-06: 0
    # Total Disallowed Loss = $14,000.00 across 7 wash sale events
    assert len(events) == 7

    total_disallowed = sum(e.disallowed_loss for e in events)
    assert total_disallowed == 14000.0

    # Exactly 1 IRA disallowance event (TC-04)
    ira_events = [e for e in events if e.is_ira_disallowance]
    assert len(ira_events) == 1
    assert ira_events[0].loss_transaction_id == "TC04-SELL-TAXABLE"
    assert ira_events[0].replacement_transaction_id == "TC04-BUY-ROTH"
    assert ira_events[0].disallowed_loss == 4000.0

    # All 7 events must have non-empty rationales
    assert all(len(e.rationale) > 20 for e in events)
