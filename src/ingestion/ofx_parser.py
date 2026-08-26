"""
Open Financial Exchange (OFX / QFX) Investment Statement Parser.
Supports both OFX 1.x (SGML-like header + unclosed tags) and OFX 2.x (XML standard).
Strictly validates transaction integrity, preventing silent data drops.
"""

from datetime import date, datetime
import logging
import re
from typing import Dict, List, Optional, Tuple

from src.models.entities import Transaction
from src.models.enums import TransactionType
from src.corporate_actions.split_adjuster import SplitAdjuster, DEFAULT_SPLIT_ADJUSTER

logger = logging.getLogger(__name__)


class OFXParser:
    """
    Parses OFX / QFX brokerage statements into canonical Transaction entities with automatic split adjustment.
    Ensures zero silent data drops: malformed transaction blocks raise explicit exceptions.
    """

    @staticmethod
    def _parse_ofx_date(date_str: str) -> date:
        """
        Parses OFX date strings formatted as YYYYMMDD or YYYYMMDDHHMMSS[.XXX][tz].
        """
        clean = re.sub(r"\[.*\]", "", date_str.strip())  # Remove timezone offset like [-5:EST]
        digits = clean[:8]
        try:
            return datetime.strptime(digits, "%Y%m%d").date()
        except ValueError as e:
            raise ValueError(f"Malformed OFX date string: '{date_str}'") from e

    @staticmethod
    def _extract_tag_value(block: str, tag: str) -> Optional[str]:
        """Extracts text content for a tag in both SGML (<TAG>val) and XML (<TAG>val</TAG>) forms."""
        # Check XML form first: <TAG>val</TAG>
        m_xml = re.search(rf"<{tag}>([^<>\r\n]+)</{tag}>", block, re.IGNORECASE)
        if m_xml:
            return m_xml.group(1).strip()
        # Check SGML form: <TAG>val\n
        m_sgml = re.search(rf"<{tag}>([^<>\r\n]+)", block, re.IGNORECASE)
        if m_sgml:
            return m_sgml.group(1).strip()
        return None

    @classmethod
    def _build_sec_map(cls, raw: str) -> Dict[str, Tuple[str, Optional[str]]]:
        """
        Extracts securities list from <SECLIST> blocks to map UNIQUEID/CUSIP to (Ticker, CUSIP).
        """
        sec_map: Dict[str, Tuple[str, Optional[str]]] = {}
        sec_blocks = re.findall(
            r"<(?:STOCKINFO|MFINFO|OTHERINFO|SECINFO|OPTINFO)>(.*?)(?=<(?:STOCKINFO|MFINFO|OTHERINFO|SECINFO|OPTINFO)|</SECLIST>|\Z)",
            raw,
            re.DOTALL | re.IGNORECASE,
        )

        for block in sec_blocks:
            unique_id = cls._extract_tag_value(block, "UNIQUEID") or cls._extract_tag_value(block, "SECID")
            id_type = (cls._extract_tag_value(block, "UNIQUEIDTYPE") or "").upper()
            ticker = cls._extract_tag_value(block, "TICKER")
            sec_name = cls._extract_tag_value(block, "SECNAME")

            if unique_id and ticker:
                cusip = unique_id if len(unique_id) == 9 and id_type != "TICKER" else None
                sec_map[unique_id] = (ticker.upper(), cusip)
            elif unique_id and id_type == "TICKER":
                sec_map[unique_id] = (unique_id.upper(), None)
            elif unique_id and sec_name:
                # Fallback if ticker tag omitted
                clean_ticker = sec_name.split()[0].upper()
                cusip = unique_id if len(unique_id) == 9 else None
                sec_map[unique_id] = (clean_ticker, cusip)

        return sec_map

    @classmethod
    def parse_ofx(
        cls,
        content_or_filepath: str,
        default_account_id: str = "ofx_account",
        split_adjuster: Optional[SplitAdjuster] = None,
        auto_split_adjust: bool = True,
    ) -> List[Transaction]:
        """
        Parses an OFX/QFX file or string into a list of Transaction entities.
        Automatically normalizes transactions for corporate stock splits (Section 3.2).
        Fails loudly on malformed transaction structures to prevent silent data loss.
        """
        if "\n" not in content_or_filepath and len(content_or_filepath) < 500:
            try:
                with open(content_or_filepath, "r", encoding="utf-8", errors="ignore") as f:
                    raw = f.read()
            except (OSError, IOError):
                raw = content_or_filepath
        else:
            raw = content_or_filepath

        # 1. Extract Account ID
        acct_id = cls._extract_tag_value(raw, "ACCTID") or default_account_id

        # 2. Extract Security Map (UNIQUEID -> (Ticker, CUSIP))
        sec_map = cls._build_sec_map(raw)

        # 3. Extract transaction blocks
        transactions: List[Transaction] = []
        tx_pattern = re.compile(
            r"<(BUYSTOCK|SELLSTOCK|BUYMF|SELLMF|REINVEST|BUYOTHER|SELLOTHER|BUYOPT|SELLOPT)>(.*?)(?=<(?:BUYSTOCK|SELLSTOCK|BUYMF|SELLMF|REINVEST|BUYOTHER|SELLOTHER|BUYOPT|SELLOPT)|</INVTRANLIST>|\Z)",
            re.DOTALL | re.IGNORECASE,
        )

        matches = tx_pattern.findall(raw)
        for idx, (tx_tag, block) in enumerate(matches):
            upper_tag = tx_tag.upper()
            is_buy = "BUY" in upper_tag or "REINVEST" in upper_tag
            tx_type = TransactionType.BUY if is_buy else TransactionType.SELL

            fitid = cls._extract_tag_value(block, "FITID") or f"OFX-{acct_id}-{idx}"
            dttrade_str = cls._extract_tag_value(block, "DTTRADE")
            if not dttrade_str:
                raise ValueError(
                    f"OFX Parsing Error: Missing required <DTTRADE> in '{tx_tag}' transaction (FITID: {fitid}) on account '{acct_id}'"
                )

            trade_date = cls._parse_ofx_date(dttrade_str)

            dtsettle_str = cls._extract_tag_value(block, "DTSETTLE")
            settle_date = cls._parse_ofx_date(dtsettle_str) if dtsettle_str else trade_date

            unique_id = cls._extract_tag_value(block, "UNIQUEID") or cls._extract_tag_value(block, "SECID")
            id_type = (cls._extract_tag_value(block, "UNIQUEIDTYPE") or "").upper()
            ticker_direct = cls._extract_tag_value(block, "TICKER")

            if ticker_direct:
                ticker = ticker_direct.upper()
                cusip = unique_id if unique_id and len(unique_id) == 9 and id_type != "TICKER" else None
            elif unique_id and unique_id in sec_map:
                ticker, cusip = sec_map[unique_id]
            elif unique_id and id_type == "TICKER":
                ticker = unique_id.upper()
                cusip = None
            elif unique_id:
                ticker = unique_id.upper()
                cusip = unique_id if len(unique_id) == 9 else None
            else:
                ticker = "UNKNOWN"
                cusip = None

            units_str = cls._extract_tag_value(block, "UNITS")
            unitprice_str = cls._extract_tag_value(block, "UNITPRICE")
            total_str = cls._extract_tag_value(block, "TOTAL")

            if not units_str and not total_str:
                raise ValueError(
                    f"OFX Parsing Error: Transaction '{fitid}' on account '{acct_id}' has neither <UNITS> nor <TOTAL>"
                )

            qty = abs(float(units_str.replace(",", "").strip())) if units_str else 0.0
            price = abs(float(unitprice_str.replace(",", "").strip())) if unitprice_str else 0.0

            # Price derivation fallback: if UNITPRICE is omitted but TOTAL and UNITS exist
            if price == 0.0 and total_str and qty > 0:
                tot_val = abs(float(total_str.replace(",", "").strip()))
                price = tot_val / qty

            if qty <= 0:
                raise ValueError(
                    f"OFX Parsing Error: Transaction '{fitid}' on account '{acct_id}' has invalid quantity '{units_str}'"
                )

            gain_str = cls._extract_tag_value(block, "GAIN") or cls._extract_tag_value(block, "REALIZEDGAIN")
            gain_loss = float(gain_str.replace(",", "").strip()) if gain_str else None

            transactions.append(Transaction(
                transaction_id=fitid,
                account_id=acct_id,
                ticker=ticker,
                cusip=cusip,
                transaction_type=tx_type,
                quantity=qty,
                price_per_share=price,
                trade_date=trade_date,
                settlement_date=settle_date,
                realized_gain_loss=gain_loss,
                unmatched_quantity=qty,
            ))

        transactions.sort(key=lambda x: (x.trade_date, x.transaction_id))

        if auto_split_adjust:
            adjuster = split_adjuster if split_adjuster is not None else DEFAULT_SPLIT_ADJUSTER
            transactions = adjuster.normalize_transactions(transactions)

        return transactions
