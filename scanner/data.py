from __future__ import annotations

import logging
import time
from datetime import datetime, time as clock_time
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

LOGGER = logging.getLogger(__name__)
REQUIRED = ["Open", "High", "Low", "Close", "Volume"]


def remove_incomplete_daily_bar(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    now = datetime.now(ZoneInfo("America/Toronto"))
    last_date = pd.Timestamp(frame.index[-1]).date()
    # Délai de sécurité après la clôture pour laisser Yahoo finaliser la séance.
    if last_date == now.date() and now.time() < clock_time(16, 20):
        return frame.iloc[:-1]
    return frame


def _split_download(raw: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    if raw.empty:
        return result
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(raw.columns.get_level_values(0))
        for symbol in symbols:
            try:
                frame = raw[symbol].copy() if symbol in level0 else raw.xs(symbol, level=1, axis=1).copy()
            except (KeyError, ValueError):
                continue
            result[symbol] = frame
    elif len(symbols) == 1:
        result[symbols[0]] = raw.copy()
    return result


def download_history(symbols: list[str], cfg: dict) -> tuple[dict[str, pd.DataFrame], dict]:
    batch_size = int(cfg["batch_size"])
    retries = int(cfg["retries"])
    histories: dict[str, pd.DataFrame] = {}
    diagnostics = {"requested": len(symbols), "downloaded": 0, "failed": []}

    for start in range(0, len(symbols), batch_size):
        batch = symbols[start : start + batch_size]
        split = {}
        last_error = ""
        for attempt in range(1, retries + 1):
            try:
                raw = yf.download(
                    tickers=batch,
                    period=cfg["period"],
                    interval=cfg["interval"],
                    auto_adjust=bool(cfg["auto_adjust"]),
                    actions=False,
                    group_by="ticker",
                    threads=True,
                    progress=False,
                    timeout=int(cfg["timeout_seconds"]),
                )
                split = _split_download(raw, batch)
                if split:
                    break
            except Exception as exc:
                last_error = str(exc)
                LOGGER.warning("Lot Yahoo tentative %s/%s: %s", attempt, retries, exc)
            time.sleep(float(cfg["pause_seconds"]) * attempt)

        for symbol in batch:
            frame = split.get(symbol)
            if frame is None or frame.empty:
                diagnostics["failed"].append({"symbol": symbol, "error": last_error or "aucune donnée"})
                continue
            frame.columns = [str(c).title() for c in frame.columns]
            if not set(REQUIRED).issubset(frame.columns):
                diagnostics["failed"].append({"symbol": symbol, "error": "colonnes OHLCV manquantes"})
                continue
            frame = frame[REQUIRED].apply(pd.to_numeric, errors="coerce").dropna(subset=["Open", "High", "Low", "Close"])
            frame["Volume"] = frame["Volume"].fillna(0)
            frame = remove_incomplete_daily_bar(frame)
            if not frame.empty:
                histories[symbol] = frame

        LOGGER.info("Téléchargement %s/%s — %s titres valides", min(start + batch_size, len(symbols)), len(symbols), len(histories))
        time.sleep(float(cfg["pause_seconds"]))

    diagnostics["downloaded"] = len(histories)
    diagnostics["coverage_pct"] = round(100 * len(histories) / max(len(symbols), 1), 2)
    return histories, diagnostics

