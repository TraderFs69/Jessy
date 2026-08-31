from __future__ import annotations

import numpy as np
import pandas as pd


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    return result.where(avg_loss.ne(0), 100.0)


def true_range(df: pd.DataFrame) -> pd.Series:
    previous_close = df["Close"].shift(1)
    return pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - previous_close).abs(),
            (df["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def atr_wilder(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def stochastic_rsi(rsi: pd.Series, period: int = 14, smooth: int = 3) -> tuple[pd.Series, pd.Series]:
    rolling_min = rsi.rolling(period).min()
    rolling_max = rsi.rolling(period).max()
    raw = 100 * (rsi - rolling_min) / (rolling_max - rolling_min).replace(0, np.nan)
    k = raw.rolling(smooth).mean()
    d = k.rolling(smooth).mean()
    return k, d


def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    ha = pd.DataFrame(index=df.index)
    ha["Close"] = (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4
    ha_open = np.empty(len(df), dtype=float)
    if len(df) == 0:
        return ha
    ha_open[0] = (float(df["Open"].iloc[0]) + float(df["Close"].iloc[0])) / 2
    for i in range(1, len(df)):
        ha_open[i] = (ha_open[i - 1] + float(ha["Close"].iloc[i - 1])) / 2
    ha["Open"] = ha_open
    ha["High"] = pd.concat([df["High"], ha["Open"], ha["Close"]], axis=1).max(axis=1)
    ha["Low"] = pd.concat([df["Low"], ha["Open"], ha["Close"]], axis=1).min(axis=1)
    ha["Green"] = ha["Close"] > ha["Open"]
    return ha


def add_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    out = df.copy()
    for period in (9, 20, 50, 100, 200):
        out[f"EMA{period}"] = out["Close"].ewm(span=period, adjust=False).mean()

    rsi_period = int(cfg["rsi_period"])
    out["RSI"] = rsi_wilder(out["Close"], rsi_period)
    out["StochK"], out["StochD"] = stochastic_rsi(out["RSI"], rsi_period)

    ema12 = out["Close"].ewm(span=12, adjust=False).mean()
    ema26 = out["Close"].ewm(span=26, adjust=False).mean()
    out["MACD"] = ema12 - ema26
    out["MACDSignal"] = out["MACD"].ewm(span=9, adjust=False).mean()
    out["MACDHistogram"] = out["MACD"] - out["MACDSignal"]

    bb_period = int(cfg["bollinger_period"])
    bb_std = float(cfg["bollinger_std"])
    out["BBMid"] = out["Close"].rolling(bb_period).mean()
    rolling_std = out["Close"].rolling(bb_period).std(ddof=0)
    out["BBUpper"] = out["BBMid"] + bb_std * rolling_std
    out["BBLower"] = out["BBMid"] - bb_std * rolling_std

    out["ATR"] = atr_wilder(out, int(cfg["atr_period"]))
    out["VolumeAvg20"] = out["Volume"].rolling(int(cfg["volume_average_period"])).mean()

    ha = heikin_ashi(out)
    out["HAOpen"] = ha["Open"]
    out["HAClose"] = ha["Close"]
    out["HAGreen"] = ha["Green"]
    return out

