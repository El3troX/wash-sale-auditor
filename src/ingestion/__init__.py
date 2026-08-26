"""
Ingestion layer for multi-broker trade ledgers, OFX files, and Plaid APIs.
"""

from src.ingestion.csv_parser import CSVParser
from src.ingestion.ofx_parser import OFXParser
from src.ingestion.plaid_client import PlaidClient
from src.ingestion.pipeline import IngestionPipeline

__all__ = [
    "CSVParser",
    "OFXParser",
    "PlaidClient",
    "IngestionPipeline",
]
