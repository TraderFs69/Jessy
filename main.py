from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import yaml

from .data import download_history
from .report import send_discord, write_outputs
from .strategy import evaluate
from .symbols import build_universe

ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    with (ROOT / "config.yml").open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def market_is_healthy(cfg: dict) -> tuple[bool, str]:
    if not cfg.get("enabled", False):
        return True, "désactivé"
    histories, _ = download_history([cfg["symbol"]], {
        "period": "2y", "interval": "1d", "batch_size": 1, "pause_seconds": 0,
        "retries": 2, "timeout_seconds": 30, "auto_adjust": True,
    })
    frame = histories.get(cfg["symbol"])
    if frame is None or len(frame) < int(cfg["ema_period"]):
        return False, "données du filtre de marché indisponibles"
    ema = frame["Close"].ewm(span=int(cfg["ema_period"]), adjust=False).mean()
    healthy = bool(frame["Close"].iloc[-1] > ema.iloc[-1])
    return healthy, f"{cfg['symbol']} {'>' if healthy else '<='} EMA{cfg['ema_period']}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    cfg = load_config()
    universe, universe_diag = build_universe(
        ROOT,
        cfg["universe"],
        timeout=int(cfg["download"]["timeout_seconds"]),
    )
    histories, download_diag = download_history(universe["yahoo_symbol"].tolist(), cfg["download"])
    healthy, market_status = market_is_healthy(cfg["market_filter"])

    lookup = universe.set_index("yahoo_symbol")
    signals = []
    if healthy:
        for symbol, history in histories.items():
            meta = lookup.loc[symbol]
            signal = evaluate(
                symbol=symbol,
                exchange=str(meta["exchange"]),
                name=str(meta["name"]),
                history=history,
                cfg=cfg["signal"],
                minimum_sessions=int(cfg["minimum_history_sessions"]),
                require_trend=bool(cfg["require_trend"]),
            )
            if signal and signal.score >= int(cfg["minimum_score"]):
                signals.append(signal.to_dict())

    diagnostics = {
        "universe": universe_diag,
        "download": download_diag,
        "market_filter": {"healthy": healthy, "status": market_status},
        "minimum_score": int(cfg["minimum_score"]),
        "signals": len(signals),
    }
    top = write_outputs(ROOT, signals, universe, diagnostics, int(cfg["top_n"]))
    send_discord(top, diagnostics, cfg["discord"])
    logging.info("Terminé — %s signaux, rapport: %s", len(signals), ROOT / "output" / "rapport_canada.md")


if __name__ == "__main__":
    main()

