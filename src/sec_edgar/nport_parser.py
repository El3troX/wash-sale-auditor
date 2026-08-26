"""
SEC Form N-PORT-P Parser for Mutual Fund and ETF Portfolio Disclosures.
Extracts portfolio constituent holdings, CUSIPs, balances, and asset weight vectors.
Uses lxml with local-name XPath for namespace resilience against varying SEC schema versions.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union
import io
from lxml import etree

from src.models.entities import AssetProfile


class NPortHolding:
    """Represents a single constituent holding inside an N-PORT filing."""

    def __init__(
        self,
        name: Optional[str] = None,
        title: Optional[str] = None,
        cusip: Optional[str] = None,
        ticker: Optional[str] = None,
        balance: float = 0.0,
        val_usd: float = 0.0,
        pct_val: float = 0.0,
    ) -> None:
        self.name = name
        self.title = title
        self.cusip = cusip
        self.ticker = ticker
        self.balance = balance
        self.val_usd = val_usd
        self.pct_val = pct_val

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "cusip": self.cusip,
            "ticker": self.ticker,
            "balance": self.balance,
            "val_usd": self.val_usd,
            "pct_val": self.pct_val,
        }


class NPortParser:
    """
    Parses SEC Form N-PORT / N-PORT-P XML filings into structured portfolio holdings.
    Form N-PORT uses the SEC XML submission schema (eis_NPORT_Filer.xsd).
    """

    @classmethod
    def parse_filing(
        cls,
        xml_content_or_path: Union[str, bytes, io.BytesIO],
        ticker: str = "FUND",
        asset_type: str = "etf",
        tracked_index: Optional[str] = None,
    ) -> AssetProfile:
        """
        Parses an N-PORT-P XML document and returns an AssetProfile with constituent holdings vector.
        """
        if isinstance(xml_content_or_path, str) and ("\n" not in xml_content_or_path and len(xml_content_or_path) < 500):
            try:
                tree = etree.parse(xml_content_or_path)
                root = tree.getroot()
            except (OSError, IOError):
                root = etree.fromstring(xml_content_or_path.encode("utf-8"))
        elif isinstance(xml_content_or_path, bytes):
            root = etree.fromstring(xml_content_or_path)
        elif isinstance(xml_content_or_path, str):
            root = etree.fromstring(xml_content_or_path.encode("utf-8"))
        else:
            tree = etree.parse(xml_content_or_path)
            root = tree.getroot()

        # Extract reporting period date if available
        rep_date_nodes = root.xpath("//*[local-name()='repPdDate']/text()")
        rep_date: Optional[date] = None
        if rep_date_nodes:
            try:
                rep_date = datetime.strptime(rep_date_nodes[0].strip(), "%Y-%m-%d").date()
            except ValueError:
                pass

        # Extract fund CUSIP / Series ID
        series_id_nodes = root.xpath("//*[local-name()='seriesId']/text()")
        fund_series_id = series_id_nodes[0].strip() if series_id_nodes else None

        # Find all investment securities (<invstOrSec>)
        inv_nodes = root.xpath("//*[local-name()='invstOrSec']")
        holdings: List[NPortHolding] = []
        holdings_vector: Dict[str, float] = {}

        total_pct = 0.0
        total_usd = 0.0

        for inv in inv_nodes:
            def _get_text(tag_name: str) -> Optional[str]:
                nodes = inv.xpath(f"./*[local-name()='{tag_name}']")
                if nodes and nodes[0].text is not None:
                    return str(nodes[0].text).strip()
                return None

            name = _get_text("name")
            title = _get_text("title")
            cusip = _get_text("cusip")
            
            # Check identifiers subtag for ticker or alternate cusip
            ticker_id = _get_text("ticker")
            if not ticker_id:
                id_ticker_nodes = inv.xpath(".//*[local-name()='ticker']/text()")
                if id_ticker_nodes:
                    ticker_id = id_ticker_nodes[0].strip().upper()

            balance_str = _get_text("balance")
            val_usd_str = _get_text("valUSD")
            pct_val_str = _get_text("pctVal")

            balance = float(balance_str) if balance_str else 0.0
            val_usd = float(val_usd_str) if val_usd_str else 0.0
            pct_val = float(pct_val_str) if pct_val_str else 0.0

            holding = NPortHolding(
                name=name,
                title=title,
                cusip=cusip,
                ticker=ticker_id,
                balance=balance,
                val_usd=val_usd,
                pct_val=pct_val,
            )
            holdings.append(holding)
            total_pct += pct_val
            total_usd += val_usd

            # Use CUSIP as primary key in vector, fallback to ticker or name
            key = cusip if cusip else (ticker_id if ticker_id else (name or f"SEC_{len(holdings)}"))
            # If pctVal is given, use it; otherwise fallback to USD value
            holdings_vector[key] = pct_val if pct_val > 0 else val_usd

        # Normalize holdings vector to sum to 1.0 if weights are non-zero
        sum_weights = sum(holdings_vector.values())
        if sum_weights > 0:
            holdings_vector = {k: v / sum_weights for k, v in holdings_vector.items()}

        return AssetProfile(
            ticker=ticker.upper(),
            cusip=None,
            asset_type=asset_type,
            holdings_vector=holdings_vector,
            tracked_index=tracked_index,
            last_updated=rep_date,
        )
