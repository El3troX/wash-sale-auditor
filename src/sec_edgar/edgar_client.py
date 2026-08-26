"""
SEC EDGAR API Client.
Complies with SEC Fair Access policy (custom User-Agent format, rate limiting <= 10 req/sec).
Retrieves fund submissions, accession numbers, and raw Form N-PORT-P XML filings.
"""

import time
from typing import Any, Dict, List, Optional, Tuple, cast
import requests

from src.models.entities import AssetProfile
from src.sec_edgar.nport_parser import NPortParser


class EdgarClient:
    """Client for SEC EDGAR API with rate limiting and automated N-PORT extraction."""

    BASE_SUBMISSION_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
    ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_clean}/{doc_name}"

    def __init__(
        self,
        user_agent: str = "PortfolioWashSaleAuditor researcher@washsale-portfolio.org",
        min_request_interval: float = 0.15,  # SEC limit is 10 req/sec max (0.10s)
    ) -> None:
        self.user_agent = user_agent
        self.min_request_interval = min_request_interval
        self._last_request_time = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
        })

    def _rate_limit(self) -> None:
        """Enforces rate limiting delay to avoid SEC EDGAR 429 throttling."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self._last_request_time = time.time()

    def get_submissions(self, cik: str) -> Dict[str, Any]:
        """
        Fetches metadata and recent filing list for a given 10-digit CIK.
        """
        self._rate_limit()
        padded_cik = str(cik).strip().zfill(10)
        url = self.BASE_SUBMISSION_URL.format(cik=padded_cik)
        resp = self.session.get(url)
        resp.raise_for_status()
        return cast(Dict[str, Any], resp.json())

    def fetch_latest_nport_xml(self, cik: str) -> Tuple[str, bytes]:
        """
        Finds the latest NPORT-P filing for a given CIK and downloads the raw XML.
        Returns (accession_number, raw_xml_bytes).
        """
        padded_cik = str(cik).strip().zfill(10)
        cik_int = int(padded_cik)
        submissions = self.get_submissions(padded_cik)

        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        nport_idx = None
        for idx, form in enumerate(forms):
            if "NPORT" in form.upper():
                nport_idx = idx
                break

        if nport_idx is None:
            raise FileNotFoundError(f"No Form N-PORT filing found in recent submissions for CIK {cik}")

        raw_accession = accessions[nport_idx]
        clean_accession = raw_accession.replace("-", "")
        # Primary doc might be xslFormNPORT-P_X01/primary_doc.xml; raw XML is primary_doc.xml
        primary_doc_name = primary_docs[nport_idx]
        if "/" in primary_doc_name:
            # Extract raw xml filename
            primary_doc_name = primary_doc_name.split("/")[-1]

        doc_url = self.ARCHIVES_URL.format(
            cik_int=cik_int,
            accession_clean=clean_accession,
            doc_name=primary_doc_name,
        )

        self._rate_limit()
        resp = self.session.get(doc_url)
        resp.raise_for_status()
        return raw_accession, resp.content

    def get_fund_asset_profile(
        self,
        cik: str,
        ticker: str,
        asset_type: str = "etf",
        tracked_index: Optional[str] = None,
    ) -> AssetProfile:
        """
        Fetches and parses the latest Form N-PORT disclosure for a fund into an AssetProfile.
        """
        _, xml_bytes = self.fetch_latest_nport_xml(cik)
        return NPortParser.parse_filing(
            xml_content_or_path=xml_bytes,
            ticker=ticker,
            asset_type=asset_type,
            tracked_index=tracked_index,
        )
