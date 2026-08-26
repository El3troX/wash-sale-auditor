"""
Broker CSV Parser supporting major broker formats and standard canonical schemas.
Supports Fidelity, Schwab, Vanguard, Robinhood, E*Trade, and Generic CSV exports.
"""

import csv
import io
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union
import pandas as pd

from src.models.entities import Transaction
from src.models.enums import TransactionType
from src.corporate_actions.split_adjuster import SplitAdjuster, DEFAULT_SPLIT_ADJUSTER


class CSVParser:
    """Parses raw CSV broker export files into canonical Transaction models with automatic split adjustment."""

    @staticmethod
    def _parse_date(date_str: Any) -> date:
        """Parses various date representations into a standard datetime.date."""
        if isinstance(date_str, date) and not isinstance(date_str, datetime):
            return date_str
        if isinstance(date_str, datetime):
            return date_str.date()
        if pd.isna(date_str) or not str(date_str).strip():
            raise ValueError(f"Invalid empty date string: {date_str}")

        clean_str = str(date_str).strip().split(" ")[0]  # Strip time component if present
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y", "%Y%m%d", "%m/%d/%y"):
            try:
                return datetime.strptime(clean_str, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Unable to parse date format for value: '{date_str}'")

    @staticmethod
    def _parse_float(val: Any) -> Optional[float]:
        """Cleans and parses numeric strings (e.g. '$1,234.56', '(100.0)', '-$50.0')."""
        if pd.isna(val) or val is None or str(val).strip() in ("", "-", "N/A", "n/a"):
            return None
        s = str(val).strip().replace("$", "").replace(",", "")
        # Handle accounting parentheses (e.g. (100.0) -> -100.0)
        if s.startswith("(") and s.endswith(")"):
            s = f"-{s[1:-1]}"
        try:
            return float(s)
        except ValueError:
            return None

    @classmethod
    def _detect_format(cls, columns: List[str]) -> str:
        """Identifies broker schema from CSV column headers."""
        cols_lower = [c.lower().strip() for c in columns]
        
        # Fidelity
        if "run date" in cols_lower or "action" in cols_lower and "symbol" in cols_lower and "settlement date" in cols_lower:
            return "fidelity"
        # Charles Schwab
        if "action" in cols_lower and "symbol" in cols_lower and "fees & comm" in cols_lower:
            return "schwab"
        # Vanguard
        if "investment name" in cols_lower or "transaction type" in cols_lower and "shares" in cols_lower:
            return "vanguard"
        # Robinhood
        if "activity date" in cols_lower and "process date" in cols_lower:
            return "robinhood"
        # Generic / Canonical
        if "trade_date" in cols_lower and "ticker" in cols_lower:
            return "canonical"
            
        return "generic"

    @classmethod
    def parse_csv(
        cls,
        filepath_or_buffer: Union[str, io.StringIO, io.BytesIO],
        default_account_id: str = "default_account",
        split_adjuster: Optional[SplitAdjuster] = None,
        auto_split_adjust: bool = True,
    ) -> List[Transaction]:
        """
        Parses a broker CSV file or string buffer into a list of Transaction entities.
        Automatically normalizes transactions for corporate stock splits (Section 3.2).
        """
        if isinstance(filepath_or_buffer, str):
            df = pd.read_csv(filepath_or_buffer, skipinitialspace=True)
        else:
            df = pd.read_csv(filepath_or_buffer, skipinitialspace=True)

        # Drop completely empty rows
        df = df.dropna(how="all")
        if df.empty:
            return []

        cols = [str(c).strip() for c in df.columns]
        df.columns = cols
        fmt = cls._detect_format(cols)

        transactions: List[Transaction] = []

        for idx, row in df.iterrows():
            tx = cls._parse_row(row, fmt, default_account_id, idx)
            if tx is not None:
                transactions.append(tx)

        # Sort transactions chronologically
        transactions.sort(key=lambda x: (x.trade_date, x.transaction_id))

        # Mandatory step: normalize transactions for corporate actions / stock splits
        if auto_split_adjust:
            adjuster = split_adjuster if split_adjuster is not None else DEFAULT_SPLIT_ADJUSTER
            transactions = adjuster.normalize_transactions(transactions)

        return transactions

    @staticmethod
    def _find_field(r: Dict[str, Any], *candidates: str) -> Any:
        """Finds field in row dict matching any candidate name, ignoring ($), (USD), spaces, etc."""
        # Exact check
        for c in candidates:
            c_clean = c.lower().strip()
            if c_clean in r:
                return r[c_clean]
        # Prefix/contains check
        for k, v in r.items():
            k_clean = k.lower().replace("($)", "").replace("(usd)", "").strip()
            for c in candidates:
                if k_clean == c.lower().strip():
                    return v
        return None

    @classmethod
    def _parse_row(
        cls,
        row: pd.Series,
        fmt: str,
        account_id: str,
        row_idx: int,
    ) -> Optional[Transaction]:
        """Maps a row to a Transaction entity according to detected broker format."""
        r = {str(k).lower().strip(): v for k, v in row.items()}
        
        # 1. Canonical format
        if fmt == "canonical":
            ticker = str(r.get("ticker", "")).strip().upper()
            if not ticker or ticker in ("NAN", "NONE", ""):
                return None
            
            raw_type = str(r.get("transaction_type", "")).strip().lower()
            if raw_type in ("buy", "b", "purchase"):
                tx_type = TransactionType.BUY
            elif raw_type in ("sell", "s", "sale"):
                tx_type = TransactionType.SELL
            else:
                return None

            trade_date = cls._parse_date(r["trade_date"])
            settle_date = cls._parse_date(r.get("settlement_date", r["trade_date"]))
            qty = abs(cls._parse_float(r.get("quantity")) or 0.0)
            price = abs(cls._parse_float(r.get("price_per_share")) or 0.0)
            if qty <= 0:
                return None

            gain_loss = cls._parse_float(r.get("realized_gain_loss"))
            cusip = str(r.get("cusip", "")).strip() if pd.notna(r.get("cusip")) else None
            if cusip in ("", "NAN", "NONE"):
                cusip = None

            tx_id = str(r.get("transaction_id", f"TX-{account_id}-{row_idx}")).strip()

            return Transaction(
                transaction_id=tx_id,
                account_id=str(r.get("account_id", account_id)),
                ticker=ticker,
                cusip=cusip,
                transaction_type=tx_type,
                quantity=qty,
                price_per_share=price,
                trade_date=trade_date,
                settlement_date=settle_date,
                realized_gain_loss=gain_loss,
                unmatched_quantity=qty,
            )

        # 2. Fidelity format
        elif fmt == "fidelity":
            action = str(r.get("action", "")).strip().upper()
            if "BOUGHT" in action or "BUY" in action or "PURCHASE" in action:
                tx_type = TransactionType.BUY
            elif "SOLD" in action or "SELL" in action:
                tx_type = TransactionType.SELL
            else:
                return None

            ticker = str(r.get("symbol", "")).strip().upper()
            if not ticker or ticker in ("NAN", "NONE", ""):
                return None

            trade_date_val = r.get("run date") or r.get("trade date") or r.get("date")
            if pd.isna(trade_date_val):
                return None
            trade_date = cls._parse_date(trade_date_val)
            settle_date_val = r.get("settlement date") or trade_date_val
            settle_date = cls._parse_date(settle_date_val)

            qty_val = cls._find_field(r, "quantity", "shares")
            price_val = cls._find_field(r, "price", "price ($)", "price (usd)")

            qty = abs(cls._parse_float(qty_val) or 0.0)
            price = abs(cls._parse_float(price_val) or 0.0)
            if qty <= 0:
                return None

            # Calculate or extract realized gain loss if available
            gain_loss_val = cls._find_field(r, "realized gain/loss", "realized gain/loss ($)", "gain/loss", "gain/loss ($)")
            gain_loss = cls._parse_float(gain_loss_val)
            cusip = str(r.get("cusip", "")).strip() if pd.notna(r.get("cusip")) else None
            if cusip in ("", "NAN", "NONE"):
                cusip = None

            return Transaction(
                transaction_id=f"FID-{account_id}-{row_idx}",
                account_id=account_id,
                ticker=ticker,
                cusip=cusip,
                transaction_type=tx_type,
                quantity=qty,
                price_per_share=price,
                trade_date=trade_date,
                settlement_date=settle_date,
                realized_gain_loss=gain_loss,
                unmatched_quantity=qty,
            )

        # 3. Charles Schwab format
        elif fmt == "schwab":
            action = str(r.get("action", "")).strip().upper()
            if "BUY" in action:
                tx_type = TransactionType.BUY
            elif "SELL" in action:
                tx_type = TransactionType.SELL
            else:
                return None

            ticker = str(r.get("symbol", "")).strip().upper()
            if not ticker or ticker in ("NAN", "NONE", ""):
                return None

            date_val = r.get("date")
            if pd.isna(date_val):
                return None
            trade_date = cls._parse_date(date_val)

            qty = abs(cls._parse_float(r.get("quantity")) or 0.0)
            price = abs(cls._parse_float(r.get("price")) or 0.0)
            if qty <= 0:
                return None

            gain_loss = cls._parse_float(r.get("gain/loss") or r.get("realized gain/loss"))
            return Transaction(
                transaction_id=f"SCHW-{account_id}-{row_idx}",
                account_id=account_id,
                ticker=ticker,
                cusip=None,
                transaction_type=tx_type,
                quantity=qty,
                price_per_share=price,
                trade_date=trade_date,
                settlement_date=trade_date,
                realized_gain_loss=gain_loss,
                unmatched_quantity=qty,
            )

        # 4. Vanguard format
        elif fmt == "vanguard":
            tx_type_str = str(r.get("transaction type", "")).strip().upper()
            if "BUY" in tx_type_str or "REINVESTMENT" in tx_type_str:
                tx_type = TransactionType.BUY
            elif "SELL" in tx_type_str:
                tx_type = TransactionType.SELL
            else:
                return None

            ticker = str(r.get("symbol", "")).strip().upper()
            if not ticker or ticker in ("NAN", "NONE", ""):
                # Try investment name
                ticker = str(r.get("investment name", "")).strip().upper()
                if not ticker or ticker in ("NAN", "NONE", ""):
                    return None

            trade_date_val = r.get("trade date") or r.get("settlement date")
            if pd.isna(trade_date_val):
                return None
            trade_date = cls._parse_date(trade_date_val)
            settle_date = cls._parse_date(r.get("settlement date") or trade_date_val)

            qty = abs(cls._parse_float(r.get("shares")) or 0.0)
            price = abs(cls._parse_float(r.get("share price")) or 0.0)
            if qty <= 0:
                return None

            return Transaction(
                transaction_id=f"VAN-{account_id}-{row_idx}",
                account_id=account_id,
                ticker=ticker,
                cusip=None,
                transaction_type=tx_type,
                quantity=qty,
                price_per_share=price,
                trade_date=trade_date,
                settlement_date=settle_date,
                realized_gain_loss=None,
                unmatched_quantity=qty,
            )

        # 5. Generic fallback
        else:
            # Look for common column aliases
            ticker_candidates = [v for k, v in r.items() if any(x in k for x in ["ticker", "symbol", "security"])]
            if not ticker_candidates or pd.isna(ticker_candidates[0]):
                return None
            ticker = str(ticker_candidates[0]).strip().upper()

            action_candidates = [v for k, v in r.items() if any(x in k for x in ["action", "type", "transaction"])]
            if not action_candidates or pd.isna(action_candidates[0]):
                return None
            act_str = str(action_candidates[0]).strip().upper()

            if "BUY" in act_str or "PURCHASE" in act_str:
                tx_type = TransactionType.BUY
            elif "SELL" in act_str:
                tx_type = TransactionType.SELL
            else:
                return None

            date_candidates = [v for k, v in r.items() if any(x in k for x in ["date", "trade_date", "time"])]
            if not date_candidates or pd.isna(date_candidates[0]):
                return None
            trade_date = cls._parse_date(date_candidates[0])

            qty_candidates = [v for k, v in r.items() if any(x in k for x in ["qty", "quantity", "shares", "units"])]
            price_candidates = [v for k, v in r.items() if any(x in k for x in ["price", "unit_price", "rate"])]

            parsed_qty = cls._parse_float(qty_candidates[0]) if qty_candidates else 0.0
            qty = abs(parsed_qty) if parsed_qty is not None else 0.0

            parsed_price = cls._parse_float(price_candidates[0]) if price_candidates else 0.0
            price = abs(parsed_price) if parsed_price is not None else 0.0
            if qty <= 0:
                return None

            gain_loss_candidates = [v for k, v in r.items() if any(x in k for x in ["gain", "loss", "pnl", "realized"])]
            gain_loss = cls._parse_float(gain_loss_candidates[0]) if gain_loss_candidates else None

            return Transaction(
                transaction_id=f"GEN-{account_id}-{row_idx}",
                account_id=account_id,
                ticker=ticker,
                cusip=None,
                transaction_type=tx_type,
                quantity=qty,
                price_per_share=price,
                trade_date=trade_date,
                settlement_date=trade_date,
                realized_gain_loss=gain_loss,
                unmatched_quantity=qty,
            )
