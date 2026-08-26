"""
Unit tests for the SEC Form N-PORT-P XML Parser.
Validates extraction of constituent holdings vectors against real and synthetic N-PORT filings.
"""

from datetime import date
import pytest

from src.sec_edgar.nport_parser import NPortParser, NPortHolding
from src.models.entities import AssetProfile


def test_parse_real_nport_filing() -> None:
    """Validates parsing against real Vanguard 500 Form N-PORT-P XML from EDGAR."""
    profile = NPortParser.parse_filing(
        "data/sample_nport_raw.xml",
        ticker="VOO",
        asset_type="etf",
        tracked_index="S&P 500",
    )

    assert isinstance(profile, AssetProfile)
    assert profile.ticker == "VOO"
    assert profile.asset_type == "etf"
    assert profile.tracked_index == "S&P 500"

    # Vanguard 500 has > 500 constituent holdings
    assert len(profile.holdings_vector) >= 500

    # Normalized weights must sum to 1.0 (within float rounding)
    total_weight = sum(profile.holdings_vector.values())
    assert pytest.approx(total_weight, rel=1e-4) == 1.0

    # Verify key CUSIP presence (e.g., GM CUSIP 37045V100, United Airlines 910047109)
    assert "37045V100" in profile.holdings_vector or "910047109" in profile.holdings_vector


def test_parse_synthetic_nport_xml() -> None:
    synthetic_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <edgarSubmission xmlns="http://www.sec.gov/edgar/nport">
        <formData>
            <genInfo>
                <repPdDate>2024-03-31</repPdDate>
            </genInfo>
            <invstOrSecs>
                <invstOrSec>
                    <name>APPLE INC</name>
                    <title>COM</title>
                    <cusip>037833100</cusip>
                    <balance>1000000</balance>
                    <valUSD>180000000.00</valUSD>
                    <pctVal>0.60</pctVal>
                </invstOrSec>
                <invstOrSec>
                    <name>MICROSOFT CORP</name>
                    <title>COM</title>
                    <cusip>594918104</cusip>
                    <balance>800000</balance>
                    <valUSD>120000000.00</valUSD>
                    <pctVal>0.40</pctVal>
                </invstOrSec>
            </invstOrSecs>
        </formData>
    </edgarSubmission>
    """
    profile = NPortParser.parse_filing(synthetic_xml, ticker="TECH", asset_type="etf")
    assert profile.ticker == "TECH"
    assert profile.last_updated == date(2024, 3, 31)
    assert len(profile.holdings_vector) == 2
    assert "037833100" in profile.holdings_vector
    assert "594918104" in profile.holdings_vector
    assert pytest.approx(profile.holdings_vector["037833100"], rel=1e-4) == 0.60
    assert pytest.approx(profile.holdings_vector["594918104"], rel=1e-4) == 0.40
