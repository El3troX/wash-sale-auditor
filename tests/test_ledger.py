"""
Unit and integration tests for Cost Basis Engine, DuckDB Ledger, and Form 8949 Exporter.
Verifies basis step-up, holding period tacking, IRA Revenue Ruling 2008-5 $0 step-up,
chained compounding basis calculations, and review-band isolation.
"""

from datetime import date
from typing import Dict, List
import pytest

from src.detection.wash_sale_engine import WashSaleDetectionEngine
from src.ledger.cost_basis import CostBasisEngine, TaxLot, ClosedDisposition
from src.ledger.duckdb_ledger import DuckDBLedger
from src.models.entities import Account, Transaction, WashSaleEvent
from src.models.enums import AccountType, TransactionType
from src.reporting.form8949 import Form8949Exporter


def test_taxable_basis_stepup_and_holding_period_tacking(
    multi_accounts: Dict[str, Account],
    tc01_dataset: List[Transaction],
) -> None:
    """
    Validates Section 6.1: Taxable replacement lot basis increases by disallowed loss ($2,000)
    and original holding period tacks onto the replacement lot.
    """
    detector = WashSaleDetectionEngine()
    wash_events = detector.detect_wash_sales(tc01_dataset, multi_accounts)
    assert len(wash_events) == 1

    engine = CostBasisEngine()
    lots, dispositions = engine.process_ledger(tc01_dataset, multi_accounts, wash_events)

    # Find the replacement lot for BUY-2 (100 shares of AAPL @ $90)
    repl_lot = next(lot for lot in lots if lot.lot_id == "LOT-TC01-BUY-2")
    assert repl_lot.original_basis == 9000.0
    # Basis stepped up by $2,000 disallowed loss: $9,000 + $2,000 = $11,000 ($110/share)
    assert repl_lot.adjusted_basis == 11000.0
    assert repl_lot.adjusted_cost_per_share == 110.0
    assert repl_lot.disallowed_loss_added == 2000.0
    assert not repl_lot.is_ira

    # Verify closed disposition on SELL-1
    assert len(dispositions) == 1
    disp = dispositions[0]
    assert disp.is_wash_sale
    assert disp.disallowed_loss == 2000.0
    assert disp.adjustment_code == "W"
    assert disp.net_gain_loss == 0.0  # Loss of $2000 disallowed -> net 0 gain/loss recognized on 8949


def test_ira_revenue_ruling_2008_5_permanent_disallowance_basis(
    multi_accounts: Dict[str, Account],
    tc04_dataset: List[Transaction],
) -> None:
    """
    Validates Section 6.2: Revenue Ruling 2008-5 Permanent Disallowance.
    Replacement lot in Vanguard Roth IRA receives $0 basis increase ($505.00/sh remains unchanged).
    """
    detector = WashSaleDetectionEngine()
    wash_events = detector.detect_wash_sales(tc04_dataset, multi_accounts)
    assert len(wash_events) == 1
    assert wash_events[0].is_ira_disallowance

    engine = CostBasisEngine()
    lots, dispositions = engine.process_ledger(tc04_dataset, multi_accounts, wash_events)

    roth_lot = next(lot for lot in lots if lot.lot_id == "LOT-TC04-BUY-ROTH")
    assert roth_lot.is_ira
    # Basis remains unadjusted at $50,500 ($505/sh); NO step-up allowed
    assert roth_lot.original_basis == 50500.0
    assert roth_lot.adjusted_basis == 50500.0
    assert roth_lot.disallowed_loss_added == 0.0
    assert roth_lot.holding_period_days_tacked == 0


def test_chained_wash_sale_compounded_basis_propagation(
    multi_accounts: Dict[str, Account],
    tc05_chained_dataset: List[Transaction],
) -> None:
    """
    Validates Section 6.1 on Chained Wash Sales (TC-05a):
    1. B0: Buy 50 NVDA @ $120 ($6,000 basis)
    2. S0: Sell 50 NVDA @ $100 (loss -$1,000 disallowed)
    3. B1: Buy 50 NVDA @ $105 (original basis $5,250 + $1,000 disallowed = $6,250 adjusted basis, $125/sh)
    4. S1: Sell 50 NVDA @ $95 (proceeds $4,750 vs adjusted basis $6,250 = loss -$1,500 disallowed)
    5. B2: Buy 50 NVDA @ $98 (original basis $4,900 + $1,500 disallowed = $6,400 adjusted basis, $128/sh)
    """
    detector = WashSaleDetectionEngine()
    wash_events = detector.detect_wash_sales(tc05_chained_dataset, multi_accounts)
    assert len(wash_events) == 2

    engine = CostBasisEngine()
    lots, dispositions = engine.process_ledger(tc05_chained_dataset, multi_accounts, wash_events)

    b1_lot = next(lot for lot in lots if lot.lot_id == "LOT-TC05-BUY-B1")
    assert b1_lot.original_basis == 5250.0  # 50 * 105
    assert b1_lot.adjusted_basis == 6250.0  # 5250 + 1000 from S0
    assert b1_lot.adjusted_cost_per_share == 125.0

    b2_lot = next(lot for lot in lots if lot.lot_id == "LOT-TC05-BUY-B2")
    assert b2_lot.original_basis == 4900.0  # 50 * 98
    # Cumulative disallowed loss propagates to B2: $4,900 + $500 (from S1) = $5,400
    assert b2_lot.adjusted_basis == 5400.0


def test_review_band_candidates_never_alter_cost_basis(
    multi_accounts: Dict[str, Account],
) -> None:
    """
    Architectural Safeguard:
    Unconfirmed review-band events (requires_manual_review = True) MUST NEVER modify cost basis.
    """
    fid = multi_accounts["fidelity_taxable"]
    txs = [
        Transaction(
            transaction_id="TX-SELL-1",
            account_id=fid.account_id,
            ticker="SECT_A",
            cusip=None,
            transaction_type=TransactionType.SELL,
            quantity=100.0,
            price_per_share=50.0,
            trade_date=date(2024, 7, 1),
            settlement_date=date(2024, 7, 3),
            realized_gain_loss=-1000.0,
        ),
        Transaction(
            transaction_id="TX-BUY-1",
            account_id=fid.account_id,
            ticker="SECT_B",
            cusip=None,
            transaction_type=TransactionType.BUY,
            quantity=100.0,
            price_per_share=55.0,
            trade_date=date(2024, 7, 10),
            settlement_date=date(2024, 7, 12),
        ),
    ]

    # Mock an unconfirmed review event
    review_event = WashSaleEvent(
        event_id="WS-REV-1",
        loss_transaction_id="TX-SELL-1",
        replacement_transaction_id="TX-BUY-1",
        matched_quantity=100.0,
        disallowed_loss=0.0,
        similarity_score=0.88,
        window_days=9,
        is_ira_disallowance=False,
        rationale="Review candidate",
        requires_manual_review=True,
        tier=3,
    )

    engine = CostBasisEngine()
    lots, dispositions = engine.process_ledger(txs, multi_accounts, [review_event])

    # Basis on BUY-1 must remain strictly unadjusted original basis
    lot = next(l for l in lots if l.lot_id == "LOT-TX-BUY-1")
    assert lot.original_basis == 5500.0
    assert lot.adjusted_basis == 5500.0
    assert lot.disallowed_loss_added == 0.0


def test_duckdb_sql_ledger_queries(
    multi_accounts: Dict[str, Account],
    full_portfolio_dataset: List[Transaction],
) -> None:
    """
    Validates DuckDB SQL analytics queries over the multi-broker tax ledger.
    """
    detector = WashSaleDetectionEngine()
    wash_events = detector.detect_wash_sales(full_portfolio_dataset, multi_accounts)

    engine = CostBasisEngine()
    lots, dispositions = engine.process_ledger(full_portfolio_dataset, multi_accounts, wash_events)

    db = DuckDBLedger()
    db.load_data(
        accounts=list(multi_accounts.values()),
        transactions=full_portfolio_dataset,
        lots=lots,
        wash_events=wash_events,
        dispositions=dispositions,
    )

    summary = db.query_wash_sales_summary()
    assert summary["confirmed_events"] == 7
    assert summary["total_disallowed_loss"] == 14000.0
    assert summary["ira_permanent_disallowances"] == 4000.0
    assert summary["taxable_basis_adjustments"] == 10000.0

    open_lots = db.query_open_lots()
    assert len(open_lots) > 0

    f8949 = db.query_form_8949_dispositions()
    assert len(f8949) > 0
    db.close()


def test_form_8949_csv_export(
    multi_accounts: Dict[str, Account],
    tc01_dataset: List[Transaction],
) -> None:
    """Validates Form 8949 CSV formatting and column headers."""
    detector = WashSaleDetectionEngine()
    wash_events = detector.detect_wash_sales(tc01_dataset, multi_accounts)

    engine = CostBasisEngine()
    _, dispositions = engine.process_ledger(tc01_dataset, multi_accounts, wash_events)

    csv_out = Form8949Exporter.export_csv(dispositions)
    assert "1a_description,1b_date_acquired,1c_date_sold" in csv_out
    assert "100.00 shs AAPL" in csv_out
    assert ",W," in csv_out  # Code W for wash sale
    assert "2000.0" in csv_out  # Adjustment amount
