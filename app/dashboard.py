"""
Multi-Broker Cross-Account Wash Sale & Tax Loss Harvesting Auditor Dashboard.
Streamlit application featuring interactive Plotly 61-day temporal timeline,
confirmed vs. review-band event segregation, lot-level ledger, and Form 8949 CSV export.
"""

from datetime import date
import io
from pathlib import Path
import sys
from typing import Dict, List

# Ensure project root is in sys.path regardless of execution working directory
root_dir = str(Path(__file__).resolve().parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.detection.wash_sale_engine import WashSaleDetectionEngine
from src.equivalence.engine import EquivalenceEngine, DEFAULT_EQUIVALENCE_ENGINE
from src.ingestion.csv_parser import CSVParser
from src.ingestion.pipeline import IngestionPipeline
from src.ledger.cost_basis import CostBasisEngine, TaxLot, ClosedDisposition
from src.ledger.duckdb_ledger import DuckDBLedger
from src.models.entities import Account, Transaction, WashSaleEvent
from src.models.enums import AccountType, TransactionType
from src.reporting.form8949 import Form8949Exporter


# Configure page layout and visual theme
st.set_page_config(
    page_title="Wash Sale & Tax Loss Harvesting Auditor",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("⚖️ Multi-Broker Cross-Account Wash Sale Auditor")
st.caption("IRC §1091 Cross-Brokerage Temporal Graph Matching & Revenue Ruling 2008-5 IRA Basis Engine")

# Disclaimer banner per non-goals convention
st.warning(
    "⚠️ **DISCLAIMER**: This application is for educational, portfolio, and research demonstration purposes only. "
    "It is not Certified Public Accountant (CPA) or IRS-certified tax advice. Consult a licensed CPA for tax filings."
)


def load_demo_portfolio() -> Tuple_Data:  # type: ignore
    pass


# Sidebar controls
st.sidebar.header("📁 Data Ingestion & Settings")
dataset_choice = st.sidebar.selectbox(
    "Select Transaction Dataset",
    [
        "Composite Multi-Broker Portfolio (All TCs)",
        "TC-01: Single Account Baseline (Pub 550)",
        "TC-02: 30-Day Lookback Window",
        "TC-03: Cross-Broker ETF Swap (VOO -> IVV)",
        "TC-04: IRA Repurchase (Rev. Rul. 2008-5)",
        "TC-05: Chained Wash Sales & Competing Sales",
        "TC-06: Same-Day Same-Lot Filter",
        "Upload Custom Broker CSV/OFX",
    ],
)

# Initialize accounts
demo_accounts = {
    "acct_fid_tax": Account("acct_fid_tax", "Fidelity", AccountType.TAXABLE),
    "acct_schw_tax": Account("acct_schw_tax", "Charles Schwab", AccountType.TAXABLE),
    "acct_van_roth": Account("acct_van_roth", "Vanguard", AccountType.ROTH_IRA),
    "acct_wf_robo": Account("acct_wf_robo", "Wealthfront", AccountType.ROBO_MANAGED),
}

transactions: List[Transaction] = []

if dataset_choice == "Upload Custom Broker CSV/OFX":
    uploaded_file = st.sidebar.file_uploader("Upload Broker Export File", type=["csv", "ofx", "qfx"])
    if uploaded_file is not None:
        pipeline = IngestionPipeline()
        content = uploaded_file.getvalue()
        if uploaded_file.name.endswith(".csv"):
            transactions = pipeline.ingest_csv(io.StringIO(content.decode("utf-8", errors="ignore")))
        else:
            transactions = pipeline.ingest_ofx(content.decode("utf-8", errors="ignore"))
        st.sidebar.success(f"Parsed {len(transactions)} transactions successfully!")
    else:
        st.info("Upload a broker CSV or OFX export file in the sidebar to run the auditor.")
        st.stop()
else:
    # Load synthetic dataset based on selection
    from tests.conftest import (
        tc01_dataset,
        tc02_dataset,
        tc03_dataset,
        tc04_dataset,
        tc05_chained_dataset,
        tc05_competing_dataset,
        tc06_dataset,
        full_portfolio_dataset,
    )
    # Recreate fixture instances
    acc_dict = {
        "fidelity_taxable": demo_accounts["acct_fid_tax"],
        "schwab_taxable": demo_accounts["acct_schw_tax"],
        "vanguard_roth": demo_accounts["acct_van_roth"],
        "wealthfront_robo": demo_accounts["acct_wf_robo"],
    }
    if dataset_choice == "TC-01: Single Account Baseline (Pub 550)":
        transactions = tc01_dataset(acc_dict)
    elif dataset_choice == "TC-02: 30-Day Lookback Window":
        transactions = tc02_dataset(acc_dict)
    elif dataset_choice == "TC-03: Cross-Broker ETF Swap (VOO -> IVV)":
        transactions = tc03_dataset(acc_dict)
    elif dataset_choice == "TC-04: IRA Repurchase (Rev. Rul. 2008-5)":
        transactions = tc04_dataset(acc_dict)
    elif dataset_choice == "TC-05: Chained Wash Sales & Competing Sales":
        transactions = tc05_chained_dataset(acc_dict) + tc05_competing_dataset(acc_dict)
    elif dataset_choice == "TC-06: Same-Day Same-Lot Filter":
        transactions = tc06_dataset(acc_dict)
    else:
        transactions = full_portfolio_dataset(
            tc01_dataset(acc_dict),
            tc02_dataset(acc_dict),
            tc03_dataset(acc_dict),
            tc04_dataset(acc_dict),
            tc05_chained_dataset(acc_dict),
            tc05_competing_dataset(acc_dict),
            tc06_dataset(acc_dict),
        )

# Execute Detection Engine
detector = WashSaleDetectionEngine()
wash_events = detector.detect_wash_sales(transactions, demo_accounts)

# Execute Cost Basis Engine
basis_engine = CostBasisEngine()
tax_lots, dispositions = basis_engine.process_ledger(transactions, demo_accounts, wash_events)

# Load into DuckDB for SQL Analytics
duckdb_ledger = DuckDBLedger()
duckdb_ledger.load_data(
    accounts=list(demo_accounts.values()),
    transactions=transactions,
    lots=tax_lots,
    wash_events=wash_events,
    dispositions=dispositions,
)
summary = duckdb_ledger.query_wash_sales_summary()

# ----------------- Top KPI Metric Cards -----------------
st.markdown("### 📊 Portfolio Audit Summary")
col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Transactions", len(transactions))
col2.metric(
    "Confirmed Disallowed Loss",
    f"${summary['total_disallowed_loss']:,.2f}",
    f"{summary['confirmed_events']} events",
)
col3.metric(
    "IRA Permanent Disallowance",
    f"${summary['ira_permanent_disallowances']:,.2f}",
    "Rev. Rul. 2008-5",
    delta_color="inverse",
)
col4.metric(
    "Review Candidates",
    f"{summary['review_candidates']}",
    "0.80-0.95 Cosine Band",
)

st.divider()

# ----------------- Confirmed vs Review-Band Wash Sales -----------------
st.markdown("### 🔍 Wash Sale Detection Audit Trail")
tab_confirmed, tab_review, tab_lots, tab_timeline, tab_8949 = st.tabs([
    "✅ Confirmed Wash Sales",
    "⚠️ Review Candidates (0.80-0.95)",
    "📦 Tax Lots & Basis Step-Up",
    "📈 61-Day Temporal Timeline",
    "📑 Form 8949 Export",
])

with tab_confirmed:
    confirmed_events = [e for e in wash_events if not e.requires_manual_review]
    if confirmed_events:
        c_data = []
        for e in confirmed_events:
            c_data.append({
                "Event ID": e.event_id,
                "Loss Sale": e.loss_transaction_id,
                "Replacement Buy": e.replacement_transaction_id,
                "Matched Shares": f"{e.matched_quantity:.2f}",
                "Disallowed Loss": f"${e.disallowed_loss:,.2f}",
                "Window Days": f"{e.window_days}d",
                "Tier": f"Tier {e.tier}",
                "IRA Branch": "🚫 Rev. Rul. 2008-5 ($0 basis step-up)" if e.is_ira_disallowance else "Taxable (Basis step-up)",
                "Explainability Rationale": e.rationale,
            })
        st.dataframe(pd.DataFrame(c_data), use_container_width=True)
    else:
        st.success("No confirmed wash sales detected in this transaction stream.")

with tab_review:
    review_events = [e for e in wash_events if e.requires_manual_review]
    if review_events:
        st.info(
            "ℹ️ **Review Band Candidates**: These asset pairs exhibit cosine similarity between 0.80 and 0.95. "
            "Under our architecture, **no loss is automatically disallowed** without manual CPA confirmation."
        )
        r_data = []
        for e in review_events:
            r_data.append({
                "Event ID": e.event_id,
                "Loss Sale": e.loss_transaction_id,
                "Replacement Buy": e.replacement_transaction_id,
                "Similarity Score": f"{e.similarity_score:.4f}",
                "Status": "Awaiting CPA Review",
                "Auto-Disallowed Amount": "$0.00",
                "Review Rationale": e.rationale,
            })
        st.dataframe(pd.DataFrame(r_data), use_container_width=True)
    else:
        st.write("No review-band candidates found.")

with tab_lots:
    st.markdown("#### Lot-Level Cost Basis & Holding Period Ledger")
    lots_data = []
    for lot in tax_lots:
        lots_data.append({
            "Lot ID": lot.lot_id,
            "Account": lot.account_id,
            "Ticker": lot.ticker,
            "Acquired Date": lot.acquired_date.isoformat(),
            "Qty": lot.quantity,
            "Original Basis": f"${lot.original_basis:,.2f}",
            "Disallowed Step-Up": f"${lot.disallowed_loss_added:,.2f}",
            "Adjusted Basis": f"${lot.adjusted_basis:,.2f}",
            "Adj Cost/Share": f"${lot.adjusted_cost_per_share:,.2f}",
            "Tacked Days": f"{lot.holding_period_days_tacked}d",
            "Account Type": "IRA ($0 step-up)" if lot.is_ira else "Taxable",
            "Status": "Closed" if lot.is_closed else "Open",
        })
    st.dataframe(pd.DataFrame(lots_data), use_container_width=True)

with tab_timeline:
    st.markdown("#### Interactive 61-Day Temporal Graph Matching")
    fig = go.Figure()

    # Plot transactions
    tx_df = pd.DataFrame([
        {
            "id": t.transaction_id,
            "date": t.trade_date,
            "type": t.transaction_type.value,
            "ticker": t.ticker,
            "account": t.account_id,
            "qty": t.quantity,
            "price": t.price_per_share,
            "gain_loss": t.realized_gain_loss,
        }
        for t in transactions
    ])

    if not tx_df.empty:
        buys = tx_df[tx_df["type"] == "buy"]
        sells = tx_df[tx_df["type"] == "sell"]

        # Add buys
        fig.add_trace(go.Scatter(
            x=buys["date"],
            y=buys["ticker"],
            mode="markers+text",
            name="Buy Transactions",
            marker=dict(size=12, color="#00C805", symbol="triangle-up"),
            text=buys["id"],
            textposition="top center",
            hoverinfo="text",
            hovertext=[f"BUY {r.qty} {r.ticker} @ ${r.price} ({r.id})<br>Date: {r.date}<br>Account: {r.account}" for _, r in buys.iterrows()],
        ))

        # Add sells
        fig.add_trace(go.Scatter(
            x=sells["date"],
            y=sells["ticker"],
            mode="markers+text",
            name="Sell Transactions",
            marker=dict(size=12, color="#FF3B30", symbol="triangle-down"),
            text=sells["id"],
            textposition="bottom center",
            hoverinfo="text",
            hovertext=[f"SELL {r.qty} {r.ticker} @ ${r.price} ({r.id})<br>Realized: ${r.gain_loss}<br>Date: {r.date}" for _, r in sells.iterrows()],
        ))

        # Add correlation arcs for confirmed wash sales
        tx_lookup = {t.transaction_id: t for t in transactions}
        for ev in confirmed_events:
            s_tx = tx_lookup.get(ev.loss_transaction_id)
            b_tx = tx_lookup.get(ev.replacement_transaction_id)
            if s_tx and b_tx:
                fig.add_trace(go.Scatter(
                    x=[s_tx.trade_date, b_tx.trade_date],
                    y=[s_tx.ticker, b_tx.ticker],
                    mode="lines+markers",
                    name=f"Wash Sale ({ev.event_id})",
                    line=dict(color="#FF9500", width=2, dash="dot"),
                    hoverinfo="text",
                    hovertext=f"Disallowed: ${ev.disallowed_loss:,.2f}<br>{ev.rationale}",
                    showlegend=False,
                ))

        fig.update_layout(
            title="Temporal Trade Map & Wash Sale Correlation Links",
            xaxis_title="Trade Date",
            yaxis_title="Security Symbol",
            template="plotly_dark",
            height=450,
            margin=dict(l=40, r=40, t=50, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

with tab_8949:
    st.markdown("#### Form 8949 Dispositions Report (IRC §1091 Adjustment Codes)")
    csv_string = Form8949Exporter.export_csv(dispositions)
    records = Form8949Exporter.generate_records(dispositions)
    if records:
        st.dataframe(pd.DataFrame(records), use_container_width=True)
        st.download_button(
            label="⬇️ Download Form 8949 CSV Report",
            data=csv_string,
            file_name=f"form_8949_audit_export_{date.today().isoformat()}.csv",
            mime="text/csv",
        )
    else:
        st.write("No capital dispositions found in this dataset.")
