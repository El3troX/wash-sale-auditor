"""
Unified Multi-Broker Ingestion Pipeline.
Coordinates CSV, OFX, and Plaid ingestion channels with mandatory corporate action split normalization.
"""

import io
from typing import Dict, List, Optional, Tuple, Union

from src.corporate_actions.split_adjuster import SplitAdjuster, DEFAULT_SPLIT_ADJUSTER
from src.ingestion.csv_parser import CSVParser
from src.ingestion.ofx_parser import OFXParser
from src.ingestion.plaid_client import PlaidClient
from src.models.entities import Account, Transaction


class IngestionPipeline:
    """
    Central ingestion orchestrator for multi-broker trade logs.
    Guarantees every ingested transaction stream passes through mandatory corporate action split normalization.
    """

    def __init__(self, split_adjuster: Optional[SplitAdjuster] = None) -> None:
        self.split_adjuster = split_adjuster if split_adjuster is not None else DEFAULT_SPLIT_ADJUSTER

    def ingest_csv(
        self,
        filepath_or_buffer: Union[str, io.StringIO, io.BytesIO],
        default_account_id: str = "default_account",
    ) -> List[Transaction]:
        """Ingests and automatically split-normalizes a CSV export."""
        return CSVParser.parse_csv(
            filepath_or_buffer,
            default_account_id=default_account_id,
            split_adjuster=self.split_adjuster,
            auto_split_adjust=True,
        )

    def ingest_ofx(
        self,
        content_or_filepath: str,
        default_account_id: str = "ofx_account",
    ) -> List[Transaction]:
        """Ingests and automatically split-normalizes an OFX/QFX statement."""
        return OFXParser.parse_ofx(
            content_or_filepath,
            default_account_id=default_account_id,
            split_adjuster=self.split_adjuster,
            auto_split_adjust=True,
        )

    def ingest_plaid_payload(
        self,
        payload: Dict[str, object],
        broker_override: Optional[str] = None,
    ) -> Tuple[List[Account], List[Transaction]]:
        """Ingests and automatically split-normalizes Plaid investments API payloads."""
        return PlaidClient.parse_plaid_payload(
            payload,
            broker_override=broker_override,
            split_adjuster=self.split_adjuster,
            auto_split_adjust=True,
        )
