import numpy as np
import pandas as pd

from scanner.indicators import atr_wilder, heikin_ashi, rsi_wilder


def test_rsi_in_strong_uptrend_is_high():
    close = pd.Series(np.arange(1.0, 50.0))
    assert rsi_wilder(close, 14).iloc[-1] == 100.0


def test_atr_is_positive():
    close = pd.Series(np.linspace(10, 20, 50))
    frame = pd.DataFrame({"Open": close - 0.1, "High": close + 0.5, "Low": close - 0.5, "Close": close})
    assert atr_wilder(frame, 14).iloc[-1] > 0


def test_heikin_ashi_length_and_columns():
    frame = pd.DataFrame({"Open": [10, 11], "High": [12, 13], "Low": [9, 10], "Close": [11, 12]})
    result = heikin_ashi(frame)
    assert len(result) == 2
    assert {"Open", "High", "Low", "Close", "Green"}.issubset(result.columns)

