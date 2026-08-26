"""
DuckDB SQL-over-Ledger Engine.
Conforms to Section 7 of the Technical Design Document.

# DUCKDB ARCHITECTURAL JUSTIFICATION (Per CLAUDE.md conventions):
# DuckDB is utilized here specifically to provide robust, declarative SQL-over-ledger
# querying capabilities (such as point-in-time open-lot basis lookups, multi-broker cross-account
# aggregations, and tax disposition filtering via SQL) for the audit and reporting layers.
# It is NOT introduced as a performance necessity for small volumes, but rather as an analytical
# relational query interface over the transaction lineage graph.
"""

from datetime import date
from typing import Any, Dict, List, Optional, cast
import duckdb

from src.ledger.cost_basis import ClosedDisposition, TaxLot
from src.models.entities import Account, Transaction, WashSaleEvent


class DuckDBLedger:
    """
    In-memory DuckDB analytics database maintaining the audited multi-broker tax ledger.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self.conn = duckdb.connect(database=db_path)
        self._init_tables()

    def _init_tables(self) -> None:
        """Initializes relational schema for accounts, transactions, lots, and wash sales."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                account_id VARCHAR PRIMARY KEY,
                broker_name VARCHAR,
                account_type VARCHAR,
                is_tax_advantaged BOOLEAN
            );
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id VARCHAR,
                account_id VARCHAR,
                ticker VARCHAR,
                cusip VARCHAR,
                transaction_type VARCHAR,
                quantity DOUBLE,
                price_per_share DOUBLE,
                trade_date DATE,
                settlement_date DATE,
                realized_gain_loss DOUBLE,
                unmatched_quantity DOUBLE,
                PRIMARY KEY (transaction_id, transaction_type, trade_date)
            );
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tax_lots (
                lot_id VARCHAR PRIMARY KEY,
                account_id VARCHAR,
                ticker VARCHAR,
                cusip VARCHAR,
                acquired_date DATE,
                quantity DOUBLE,
                remaining_quantity DOUBLE,
                original_basis DOUBLE,
                adjusted_basis DOUBLE,
                disallowed_loss_added DOUBLE,
                holding_period_days_tacked INTEGER,
                is_ira BOOLEAN,
                is_closed BOOLEAN,
                closed_date DATE
            );
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS wash_sale_events (
                event_id VARCHAR PRIMARY KEY,
                loss_transaction_id VARCHAR,
                replacement_transaction_id VARCHAR,
                matched_quantity DOUBLE,
                disallowed_loss DOUBLE,
                similarity_score DOUBLE,
                window_days INTEGER,
                is_ira_disallowance BOOLEAN,
                requires_manual_review BOOLEAN,
                tier INTEGER,
                rationale VARCHAR
            );
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS dispositions (
                disposition_id VARCHAR PRIMARY KEY,
                lot_id VARCHAR,
                account_id VARCHAR,
                ticker VARCHAR,
                acquired_date DATE,
                sold_date DATE,
                quantity DOUBLE,
                proceeds DOUBLE,
                cost_basis DOUBLE,
                disallowed_loss DOUBLE,
                net_gain_loss DOUBLE,
                is_wash_sale BOOLEAN,
                is_ira BOOLEAN,
                adjustment_code VARCHAR,
                holding_period_days INTEGER
            );
        """)

    def load_data(
        self,
        accounts: List[Account],
        transactions: List[Transaction],
        lots: List[TaxLot],
        wash_events: List[WashSaleEvent],
        dispositions: List[ClosedDisposition],
    ) -> None:
        """Loads entities into DuckDB tables."""
        # Clear existing data
        for table in ("accounts", "transactions", "tax_lots", "wash_sale_events", "dispositions"):
            self.conn.execute(f"DELETE FROM {table}")

        # Insert accounts
        for a in accounts:
            self.conn.execute(
                "INSERT INTO accounts VALUES (?, ?, ?, ?)",
                [a.account_id, a.broker_name, a.account_type.value, a.account_type.is_tax_advantaged],
            )

        # Insert transactions
        for t in transactions:
            self.conn.execute(
                "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    t.transaction_id,
                    t.account_id,
                    t.ticker,
                    t.cusip,
                    t.transaction_type.value,
                    t.quantity,
                    t.price_per_share,
                    t.trade_date,
                    t.settlement_date,
                    t.realized_gain_loss,
                    t.unmatched_quantity,
                ],
            )

        # Insert lots
        for lot in lots:
            self.conn.execute(
                "INSERT INTO tax_lots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    lot.lot_id,
                    lot.account_id,
                    lot.ticker,
                    lot.cusip,
                    lot.acquired_date,
                    lot.quantity,
                    lot.remaining_quantity,
                    lot.original_basis,
                    lot.adjusted_basis,
                    lot.disallowed_loss_added,
                    lot.holding_period_days_tacked,
                    lot.is_ira,
                    lot.is_closed,
                    lot.closed_date,
                ],
            )

        # Insert wash sale events
        for ev in wash_events:
            self.conn.execute(
                "INSERT INTO wash_sale_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ev.event_id,
                    ev.loss_transaction_id,
                    ev.replacement_transaction_id,
                    ev.matched_quantity,
                    ev.disallowed_loss,
                    ev.similarity_score,
                    ev.window_days,
                    ev.is_ira_disallowance,
                    ev.requires_manual_review,
                    ev.tier,
                    ev.rationale,
                ],
            )

        # Insert dispositions
        for d in dispositions:
            self.conn.execute(
                "INSERT INTO dispositions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    d.disposition_id,
                    d.lot_id,
                    d.account_id,
                    d.ticker,
                    d.acquired_date,
                    d.sold_date,
                    d.quantity,
                    d.proceeds,
                    d.cost_basis,
                    d.disallowed_loss,
                    d.net_gain_loss,
                    d.is_wash_sale,
                    d.is_ira,
                    d.adjustment_code,
                    d.holding_period_days,
                ],
            )

    def query_open_lots(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Queries open tax lots with current adjusted cost basis."""
        sql = "SELECT * FROM tax_lots WHERE remaining_quantity > 0"
        params: List[Any] = []
        if account_id:
            sql += " AND account_id = ?"
            params.append(account_id)
        sql += " ORDER BY acquired_date, ticker"
        df = self.conn.execute(sql, params).fetchdf()
        return cast(List[Dict[str, Any]], df.to_dict(orient="records"))

    def query_wash_sales_summary(self) -> Dict[str, Any]:
        """Calculates portfolio-wide wash sale audit statistics using SQL aggregation."""
        res = self.conn.execute("""
            SELECT
                COUNT(*) AS total_events,
                COUNT(*) FILTER (WHERE requires_manual_review = FALSE) AS confirmed_events,
                COUNT(*) FILTER (WHERE requires_manual_review = TRUE) AS review_candidates,
                COALESCE(SUM(disallowed_loss) FILTER (WHERE requires_manual_review = FALSE), 0.0) AS total_disallowed_loss,
                COALESCE(SUM(disallowed_loss) FILTER (WHERE is_ira_disallowance = TRUE AND requires_manual_review = FALSE), 0.0) AS ira_permanent_disallowances,
                COALESCE(SUM(disallowed_loss) FILTER (WHERE is_ira_disallowance = FALSE AND requires_manual_review = FALSE), 0.0) AS taxable_basis_adjustments
            FROM wash_sale_events
        """).fetchone()

        if res is None:
            return {
                "total_events": 0,
                "confirmed_events": 0,
                "review_candidates": 0,
                "total_disallowed_loss": 0.0,
                "ira_permanent_disallowances": 0.0,
                "taxable_basis_adjustments": 0.0,
            }

        return {
            "total_events": int(res[0]),
            "confirmed_events": int(res[1]),
            "review_candidates": int(res[2]),
            "total_disallowed_loss": float(res[3]),
            "ira_permanent_disallowances": float(res[4]),
            "taxable_basis_adjustments": float(res[5]),
        }

    def query_form_8949_dispositions(self) -> List[Dict[str, Any]]:
        """Queries capital dispositions formatted for IRS Form 8949 reporting."""
        df = self.conn.execute("""
            SELECT
                ticker AS description,
                acquired_date,
                sold_date,
                proceeds,
                cost_basis,
                adjustment_code,
                disallowed_loss AS adjustment_amount,
                net_gain_loss
            FROM dispositions
            ORDER BY sold_date, description
        """).fetchdf()
        return cast(List[Dict[str, Any]], df.to_dict(orient="records"))

    def close(self) -> None:
        self.conn.close()
