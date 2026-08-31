from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests


def write_outputs(root: Path, signals: list[dict], universe: pd.DataFrame, diagnostics: dict, top_n: int) -> pd.DataFrame:
    output = root / "output"
    output.mkdir(parents=True, exist_ok=True)
    columns = [
        "symbol", "exchange", "name", "date", "score", "close", "ema_rebound", "rsi", "stoch_k",
        "macd_histogram", "atr", "relative_volume", "stop", "target_1", "target_2", "risk_pct",
        "higher_low", "pivot_breakout", "reasons",
    ]
    frame = pd.DataFrame(signals, columns=columns)
    if not frame.empty:
        frame = frame.sort_values(["score", "relative_volume", "symbol"], ascending=[False, False, True])
    top = frame.head(top_n).copy()
    frame.to_csv(output / "signaux_canada.csv", index=False)
    top.to_csv(output / "top_signaux_canada.csv", index=False)
    universe.to_csv(output / "univers_canada.csv", index=False)

    now = datetime.now(ZoneInfo("America/Toronto"))
    lines = [
        "# Scanner swing — marché canadien",
        "",
        f"Généré le **{now:%Y-%m-%d à %H:%M} HE**.",
        f"Univers : **{len(universe)}** symboles. Données valides : **{diagnostics['download']['downloaded']}**. Signaux ≥ seuil : **{len(frame)}**.",
        "",
    ]
    warnings = diagnostics.get("universe", {}).get("warnings", [])
    if warnings:
        lines.extend(["> ⚠️ " + " | ".join(warnings), ""])
    if top.empty:
        lines.append("Aucun signal ne satisfait les critères aujourd'hui.")
    else:
        lines.extend([
            "| Rang | Symbole | Score | Prix | RSI | Rebond | Vol. relatif | Stop | Cible 2R |",
            "|---:|---|---:|---:|---:|---|---:|---:|---:|",
        ])
        for rank, row in enumerate(top.itertuples(index=False), 1):
            lines.append(f"| {rank} | {row.symbol} | {row.score} | {row.close:.2f} | {row.rsi:.1f} | {row.ema_rebound} | {row.relative_volume:.2f}× | {row.stop:.2f} | {row.target_1:.2f} |")
        lines.extend(["", "## Raisons", ""])
        for row in top.itertuples(index=False):
            lines.append(f"- **{row.symbol} — {row.score}/100 :** {row.reasons}")
    (output / "rapport_canada.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output / "scan_diagnostics.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return top


def send_discord(top: pd.DataFrame, diagnostics: dict, cfg: dict) -> None:
    if not cfg.get("enabled", False):
        return
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        return
    if top.empty:
        description = "Aucun signal n'atteint le score minimal aujourd'hui."
    else:
        blocks = []
        for rank, row in enumerate(top.head(10).itertuples(index=False), 1):
            blocks.append(
                f"**{rank}. {row.symbol} — {row.score}/100**\n"
                f"Prix {row.close:.2f} | RSI {row.rsi:.1f} | Rebond {row.ema_rebound} | Vol. {row.relative_volume:.2f}×\n"
                f"Stop {row.stop:.2f} | Cible 2R {row.target_1:.2f}"
            )
        description = "\n\n".join(blocks)
    payload = {
        "username": cfg.get("username", "Scanner Canada"),
        "embeds": [{
            "title": "Scanner swing — TSX / TSXV / CSE / NEO",
            "description": description[:4000],
            "color": 0xD4AF37,
            "footer": {"text": f"Couverture Yahoo: {diagnostics['download']['coverage_pct']}% — signal technique, pas un conseil financier"},
        }],
    }
    response = requests.post(webhook, json=payload, timeout=20)
    response.raise_for_status()
