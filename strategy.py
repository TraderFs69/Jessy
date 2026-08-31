from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .indicators import add_indicators


@dataclass
class Signal:
    symbol: str
    exchange: str
    name: str
    date: str
    score: int
    close: float
    ema_rebound: str
    rsi: float
    stoch_k: float
    macd_histogram: float
    atr: float
    relative_volume: float
    stop: float
    target_1: float
    target_2: float
    risk_pct: float
    higher_low: bool
    pivot_breakout: bool
    reasons: str

    def to_dict(self) -> dict:
        return asdict(self)


def _crossed_up(a: pd.Series, b: pd.Series | float, lookback: int = 1) -> bool:
    rhs = pd.Series(b, index=a.index) if np.isscalar(b) else b
    crosses = (a > rhs) & (a.shift(1) <= rhs.shift(1))
    return bool(crosses.tail(lookback).fillna(False).any())


def _pivots(values: pd.Series, left: int, right: int, kind: str) -> list[tuple[int, float]]:
    found = []
    array = values.to_numpy(dtype=float)
    for i in range(left, len(array) - right):
        window = array[i - left : i + right + 1]
        if not np.isfinite(window).all():
            continue
        if kind == "low" and array[i] == np.min(window) and np.sum(window == array[i]) == 1:
            found.append((i, float(array[i])))
        if kind == "high" and array[i] == np.max(window) and np.sum(window == array[i]) == 1:
            found.append((i, float(array[i])))
    return found


def evaluate(symbol: str, exchange: str, name: str, history: pd.DataFrame, cfg: dict, minimum_sessions: int, require_trend: bool) -> Signal | None:
    if len(history) < minimum_sessions:
        return None
    df = add_indicators(history, cfg).dropna(subset=["EMA200", "RSI", "ATR", "BBLower"])
    if len(df) < 3:
        return None
    current = df.iloc[-1]
    previous = df.iloc[-2]
    close = float(current["Close"])
    atr = float(current["ATR"])
    if close <= 0 or atr <= 0 or not np.isfinite([close, atr]).all():
        return None

    trend = close > current["EMA50"] > current["EMA200"]
    if require_trend and not trend:
        return None

    score = 20 if trend else 0
    reasons = []
    if trend:
        reasons.append("prix > EMA50 > EMA200")

    lookback = int(cfg["rebound_lookback"])
    tolerance = float(cfg["rebound_atr_tolerance"])
    recent = df.tail(lookback)
    rebounds = []
    for period in (9, 20, 50):
        ema = recent[f"EMA{period}"]
        touched = ((recent["Low"] - ema).abs() <= recent["ATR"] * tolerance) | ((recent["Low"] <= ema) & (recent["High"] >= ema))
        if touched.any() and close > current[f"EMA{period}"]:
            rebounds.append(f"EMA{period}")
    if rebounds:
        score += 15
        reasons.append("rebond " + "/".join(rebounds))

    rsi = df["RSI"]
    rsi_setup = float(cfg["rsi_setup_level"])
    rsi_current_ok = float(cfg["rsi_current_min"]) <= current["RSI"] <= float(cfg["rsi_current_max"])
    rsi_recovery = rsi_current_ok and (rsi.tail(6).min() <= rsi_setup) and current["RSI"] > previous["RSI"]
    if rsi_recovery:
        score += 15
        reasons.append("RSI en redressement")

    stoch_cross = _crossed_up(df["StochK"], df["StochD"], lookback=3) and df["StochK"].tail(5).min() <= float(cfg["stoch_oversold"])
    if stoch_cross:
        score += 5
        reasons.append("croisement Stoch RSI")

    ha_flip = bool(current["HAGreen"]) and not bool(previous["HAGreen"])
    if ha_flip:
        score += 10
        reasons.append("Heikin-Ashi rouge vers vert")

    price_confirmation = close > float(previous["High"])
    if price_confirmation:
        score += 15
        reasons.append("clôture au-dessus du sommet précédent")

    structure = df.tail(int(cfg["structure_lookback"])).reset_index(drop=True)
    left, right = int(cfg["pivot_left"]), int(cfg["pivot_right"])
    lows = _pivots(structure["Low"], left, right, "low")
    highs = _pivots(structure["High"], left, right, "high")
    higher_low = len(lows) >= 2 and lows[-1][1] > lows[-2][1]
    pivot_breakout = bool(highs and close > highs[-1][1])
    if higher_low or pivot_breakout:
        score += 10
        reasons.append("Higher Low" if higher_low else "cassure de pivot")

    relative_volume = float(current["Volume"] / current["VolumeAvg20"]) if current["VolumeAvg20"] > 0 else 0.0
    if relative_volume > 1:
        score += 5
        reasons.append("volume supérieur à la moyenne")

    recent_bb = df.tail(lookback)
    bb_reentry = bool(((recent_bb["Low"] <= recent_bb["BBLower"]) | (recent_bb["Close"] <= recent_bb["BBLower"])).any() and close > current["BBLower"])
    if bb_reentry:
        score += 5
        reasons.append("réintégration Bollinger")

    swing_low = lows[-1][1] if lows else float(df["Low"].tail(10).min())
    stop = min(swing_low - 0.10 * atr, close - float(cfg["stop_atr"]) * atr)
    risk = close - stop
    if risk <= 0:
        return None
    target_1 = close + float(cfg["reward_risk_target_1"]) * risk
    target_2 = close + float(cfg["reward_risk_target_2"]) * risk

    return Signal(
        symbol=symbol,
        exchange=exchange,
        name=name,
        date=str(pd.Timestamp(df.index[-1]).date()),
        score=int(score),
        close=round(close, 4),
        ema_rebound="/".join(rebounds) if rebounds else "—",
        rsi=round(float(current["RSI"]), 2),
        stoch_k=round(float(current["StochK"]), 2),
        macd_histogram=round(float(current["MACDHistogram"]), 4),
        atr=round(atr, 4),
        relative_volume=round(relative_volume, 2),
        stop=round(stop, 4),
        target_1=round(target_1, 4),
        target_2=round(target_2, 4),
        risk_pct=round(100 * risk / close, 2),
        higher_low=higher_low,
        pivot_breakout=pivot_breakout,
        reasons="; ".join(reasons),
    )

