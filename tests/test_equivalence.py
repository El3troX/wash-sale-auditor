"""
Unit and integration tests for 3-Tier Asset Equivalence Engine.
Validates Tier 1 exact matching, Tier 2 index tracking lookup, Tier 3 synthetic vectors,
and Tier 3 real N-PORT parser XML integration.
"""

from datetime import date
import pytest

from src.equivalence.engine import EquivalenceEngine, EquivalenceResult
from src.equivalence.tier1 import Tier1ExactMatcher
from src.equivalence.tier2 import Tier2IndexMatcher
from src.equivalence.tier3 import Tier3CosineSimilarityMatcher
from src.models.entities import AssetProfile
from src.sec_edgar.nport_parser import NPortParser


def test_tier1_exact_cusip_match() -> None:
    """Validates Tier 1 exact CUSIP match takes precedence."""
    matcher = Tier1ExactMatcher()
    is_match, score, rationale = matcher.match(
        ticker1="AAPL",
        ticker2="AAPL_RENAMED",
        cusip1="037833100",
        cusip2="037833100",
    )
    assert is_match
    assert score == 1.0
    assert "CUSIP match (037833100)" in rationale


def test_tier1_exact_ticker_fallback() -> None:
    """Validates Tier 1 ticker exact match when CUSIP is missing."""
    matcher = Tier1ExactMatcher()
    is_match, score, rationale = matcher.match(
        ticker1="NVDA",
        ticker2="NVDA",
        cusip1=None,
        cusip2=None,
    )
    assert is_match
    assert score == 1.0
    assert "Exact Ticker match (NVDA)" in rationale


def test_tier1_cusip_mismatch() -> None:
    """Validates that distinct valid CUSIPs fail Tier 1."""
    matcher = Tier1ExactMatcher()
    is_match, score, _ = matcher.match(
        ticker1="AAPL",
        ticker2="MSFT",
        cusip1="037833100",
        cusip2="594918104",
    )
    assert not is_match
    assert score == 0.0


def test_tier2_index_tracking_pairs() -> None:
    """Validates Tier 2 ETF-to-index tracking equivalence across major pairs."""
    matcher = Tier2IndexMatcher()

    # S&P 500 family
    m1, s1, r1 = matcher.match("VOO", "IVV")
    assert m1 and s1 == 1.0 and "S&P 500" in r1

    m2, s2, r2 = matcher.match("SPY", "SPLG")
    assert m2 and s2 == 1.0 and "S&P 500" in r2

    # Nasdaq-100 family
    m3, s3, r3 = matcher.match("QQQ", "QQQM")
    assert m3 and s3 == 1.0 and "Nasdaq-100" in r3

    # Total US Market family
    m4, s4, r4 = matcher.match("VTI", "ITOT")
    assert m4 and s4 == 1.0

    # Aggregate Bond family
    m5, s5, r5 = matcher.match("BND", "AGG")
    assert m5 and s5 == 1.0

    # Semiconductor family
    m6, s6, r6 = matcher.match("SMH", "SOXX")
    assert m6 and s6 == 1.0

    # Non-equivalent ETFs
    m_diff, s_diff, _ = matcher.match("VOO", "QQQ")
    assert not m_diff and s_diff == 0.0


def test_tier3_synthetic_holdings_vectors() -> None:
    """Validates Tier 3 cosine similarity calculations over synthetic vectors."""
    matcher = Tier3CosineSimilarityMatcher()

    # Identical vectors -> 1.0
    vec_a = {"AAPL": 0.5, "MSFT": 0.5}
    vec_b = {"AAPL": 0.5, "MSFT": 0.5}
    assert pytest.approx(matcher.compute_cosine_similarity(vec_a, vec_b), rel=1e-4) == 1.0

    # Orthogonal vectors -> 0.0
    vec_c = {"NVDA": 0.6, "AMD": 0.4}
    assert matcher.compute_cosine_similarity(vec_a, vec_c) == 0.0

    # Overlapping vectors in review band [0.80, 0.95)
    # Vec 1: AAPL 0.70, MSFT 0.30
    # Vec 2: AAPL 0.90, MSFT 0.10
    # dot = 0.63 + 0.03 = 0.66
    # norm1 = sqrt(0.49 + 0.09) = sqrt(0.58) = 0.76157
    # norm2 = sqrt(0.81 + 0.01) = sqrt(0.82) = 0.90553
    # sim = 0.66 / (0.76157 * 0.90553) = 0.66 / 0.6896 = ~0.957
    prof1 = AssetProfile(
        ticker="FUND1",
        asset_type="etf",
        holdings_vector={"AAPL": 0.60, "MSFT": 0.20, "GOOGL": 0.20},
        last_updated=date(2024, 1, 1),
    )
    prof2 = AssetProfile(
        ticker="FUND2",
        asset_type="etf",
        holdings_vector={"AAPL": 0.60, "MSFT": 0.40},
        last_updated=date(2024, 1, 1),
    )
    is_cand, score, req_review, rationale = matcher.match(prof1, prof2)
    assert is_cand
    assert 0.80 <= score < 0.95
    assert req_review  # Review band must require review
    assert "Tier 3 Review Band" in rationale


def test_tier3_real_nport_parser_integration() -> None:
    """
    Integration test: Runs Tier 3 similarity against real N-PORT output parsed by NPortParser.
    Validates end-to-end integration from raw EDGAR XML to cosine similarity scoring.
    """
    engine = EquivalenceEngine()

    # 1. Parse real Vanguard 500 N-PORT filing (519 holdings)
    voo_profile = NPortParser.parse_filing(
        "data/sample_nport_raw.xml",
        ticker="VOO_REAL",
        asset_type="etf",
        tracked_index="S&P 500",
    )
    engine.register_asset_profile(voo_profile)

    # 2. Construct a correlated S&P 500 ETF profile sharing the parsed constituent CUSIPs with tracking variation
    correlated_vector = {
        c: w * (0.98 if idx % 2 == 0 else 1.02)
        for idx, (c, w) in enumerate(voo_profile.holdings_vector.items())
    }
    tot = sum(correlated_vector.values())
    correlated_vector = {c: w / tot for c, w in correlated_vector.items()}

    ivv_simulated = AssetProfile(
        ticker="IVV_SIM",
        asset_type="etf",
        holdings_vector=correlated_vector,
        last_updated=date(2024, 3, 31),
    )
    engine.register_asset_profile(ivv_simulated)

    result = engine.evaluate("VOO_REAL", "IVV_SIM")
    assert result.is_equivalent
    assert result.tier == 3
    assert result.similarity_score >= 0.95
    assert "Tier 3 Cosine Similarity" in result.rationale
