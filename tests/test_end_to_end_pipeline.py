"""
Full End-to-End Pipeline Integration Test.
Exercises the entire lifecycle:
Raw Multi-Broker CSV/OFX Ingestion -> Split Normalization -> 3-Tier Equivalence ->
Wash Sale Temporal Graph Matching -> Lot-Level Cost Basis Propagation ->
DuckDB SQL Ledger -> Form 8949 CSV Report Export.
"""

from datetime import date
import io
from typing import Dict, List
import pytest

from src.detection.wash_sale_engine import WashSaleDetectionEngine
from src.equivalence.engine import EquivalenceEngine
from src.ingestion.pipeline import IngestionPipeline
from src.ledger.cost_basis import CostBasisEngine
from src.ledger.duckdb_ledger import DuckDBLedger
from src.models.entities import Account, Transaction
from src.models.enums import AccountType
from src.reporting.form8949 import Form8949Exporter


def test_full_end_to_end_multi_broker_pipeline() -> None:
    """
    True End-to-End Pipeline Integration:
    1. Ingest raw Fidelity CSV and raw Schwab CSV from disk.
    2. Normalize and split-adjust transactions.
    3. Run 3-Tier Equivalence & Wash Sale Detection across the merged multi-broker stream.
    4. Compute lot-level cost basis step-up and holding period propagation.
    5. Query DuckDB SQL analytics ledger.
    6. Export official IRS Form 8949 CSV report and assert on final generated tax records.
    """
    pipeline = IngestionPipeline()

    # 1. Ingest raw CSV files
    fidelity_txs = pipeline.ingest_csv("data/sample_fidelity.csv", default_account_id="acct_fid_tax")
    schwab_txs = pipeline.ingest_csv("data/sample_schwab.csv", default_account_id="acct_schw_tax")

    all_txs = fidelity_txs + schwab_txs
    assert len(all_txs) == 7

    # Multi-broker accounts definition
    accounts = {
        "acct_fid_tax": Account("acct_fid_tax", "Fidelity", AccountType.TAXABLE),
        "acct_schw_tax": Account("acct_schw_tax", "Charles Schwab", AccountType.TAXABLE),
    }

    # 2. Execute Detection Engine (Tier 1 & Tier 2)
    engine = EquivalenceEngine()
    detector = WashSaleDetectionEngine(equivalence_engine=engine)
    wash_events = detector.detect_wash_sales(all_txs, accounts)

    # Expected wash sales:
    # - Fidelity AAPL loss sell (2024-02-20, 100 shs @ -$1500) matched with Schwab AAPL buy (2024-03-10, 50 shs)
    #   -> 50 shares matched @ $15/sh = $750.00 disallowed loss (Tier 1 Exact Match)
    # - Fidelity VOO loss sell (2024-03-25, 50 shs @ -$1000) matched with Schwab IVV buy (2024-03-28, 50 shs)
    #   -> 50 shares matched @ $20/sh = $1000.00 disallowed loss (Tier 2 Index Tracking Equivalence)
    assert len(wash_events) == 2

    aapl_event = next(e for e in wash_events if "AAPL" in e.rationale)
    assert aapl_event.matched_quantity == 50.0
    assert aapl_event.disallowed_loss == 750.0
    assert aapl_event.tier == 1
    assert not aapl_event.requires_manual_review

    voo_ivv_event = next(e for e in wash_events if "VOO" in e.rationale)
    assert voo_ivv_event.matched_quantity == 50.0
    assert voo_ivv_event.disallowed_loss == 1000.0
    assert voo_ivv_event.tier == 2
    assert not voo_ivv_event.requires_manual_review

    # 3. Cost Basis Propagation & Lot Ledger
    basis_engine = CostBasisEngine()
    tax_lots, dispositions = basis_engine.process_ledger(all_txs, accounts, wash_events)

    # Verify stepped-up cost basis on Schwab replacement lots:
    # Schwab AAPL replacement lot (50 shs @ $172.50 = $8,625 + $750 disallowed = $9,375 adjusted basis)
    schwab_aapl_lot = next(l for l in tax_lots if l.account_id == "acct_schw_tax" and l.ticker == "AAPL")
    assert schwab_aapl_lot.original_basis == 8625.0
    assert schwab_aapl_lot.adjusted_basis == 9375.0
    assert schwab_aapl_lot.disallowed_loss_added == 750.0

    # Schwab IVV replacement lot (50 shs @ $442 = $22,100 + $1,000 disallowed = $23,100 adjusted basis)
    schwab_ivv_lot = next(l for l in tax_lots if l.account_id == "acct_schw_tax" and l.ticker == "IVV")
    assert schwab_ivv_lot.original_basis == 22100.0
    assert schwab_ivv_lot.adjusted_basis == 23100.0
    assert schwab_ivv_lot.disallowed_loss_added == 1000.0

    # 4. DuckDB Analytics Database
    db = DuckDBLedger()
    db.load_data(
        accounts=list(accounts.values()),
        transactions=all_txs,
        lots=tax_lots,
        wash_events=wash_events,
        dispositions=dispositions,
    )
    summary = db.query_wash_sales_summary()
    assert summary["confirmed_events"] == 2
    assert summary["total_disallowed_loss"] == 1750.0
    assert summary["taxable_basis_adjustments"] == 1750.0
    db.close()

    # 5. Form 8949 CSV Report Export & Field Assertions
    csv_report = Form8949Exporter.export_csv(dispositions)
    assert "1a_description,1b_date_acquired,1c_date_sold,1d_proceeds,1e_cost_basis,1f_code,1g_adjustment_amount,1h_gain_loss" in csv_report
    # Disallowed wash sales carry Code 'W'
    assert "100.00 shs AAPL,2024-01-15,2024-02-20,17000.0,18500.0,W,750.0,-750.0" in csv_report
    assert "50.00 shs VOO,2024-03-05,2024-03-25,22000.0,23000.0,W,1000.0,0.0" in csv_report
