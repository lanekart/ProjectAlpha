from alpha.analysis.rankings.momentum import MomentumRanker


def test_momentum_ranker_runs():
    data = {
        "symbol": ["A", "B", "C"],
        "open": [100, 200, 300],
        "close": [110, 180, 330],
        "volume": [1000, 5000, 2000],
    }

    df = MomentumRanker().rank(__import__("pandas").DataFrame(data))

    assert len(df) <= 20
    assert "momentum_score" in df.columns
