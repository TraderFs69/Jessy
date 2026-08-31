from __future__ import annotations

import io
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

TMX_DIRECTORY_PAGE = "https://www.tsx.com/en/listings/listing-with-us/listed-company-directory"
CSE_DIRECTORY_PAGE = "https://thecse.com/listing/listed-companies/"


def yahoo_symbol(symbol: str, exchange: str) -> str:
    symbol = str(symbol).strip().upper()
    if not symbol:
        return ""
    if symbol.endswith((".TO", ".V", ".CN", ".NE")):
        return symbol
    # Yahoo utilise un tiret pour les catégories et les unités canadiennes.
    symbol = symbol.replace("/", "-").replace(".", "-").replace(" ", "-")
    suffix = {"TSX": ".TO", "TSXV": ".V", "CSE": ".CN", "NEO": ".NE"}.get(exchange.upper(), "")
    return f"{symbol}{suffix}"


def _get(url: str, timeout: int) -> requests.Response:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 Trading-en-Action Canadian scanner/1.0"},
    )
    response.raise_for_status()
    return response


def _standardize_frame(frame: pd.DataFrame, default_exchange: str = "") -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "exchange", "name", "security_type"])
    frame = frame.copy()
    normalized = {str(c).strip().lower(): c for c in frame.columns}

    def find_column(options: tuple[str, ...]):
        for key, original in normalized.items():
            if any(option in key for option in options):
                return original
        return None

    symbol_col = find_column(("ticker", "symbol"))
    exchange_col = find_column(("exchange", "market"))
    name_col = find_column(("company", "issuer", "name"))
    type_col = find_column(("security type", "instrument type", "issue type", "type"))
    if symbol_col is None:
        return pd.DataFrame(columns=["symbol", "exchange", "name", "security_type"])

    out = pd.DataFrame()
    out["symbol"] = frame[symbol_col].astype(str).str.strip()
    out["exchange"] = (
        frame[exchange_col].astype(str).str.strip().str.upper() if exchange_col is not None else default_exchange
    )
    out["name"] = frame[name_col].astype(str).str.strip() if name_col is not None else ""
    out["security_type"] = frame[type_col].astype(str).str.strip() if type_col is not None else ""
    out["exchange"] = out["exchange"].replace(
        {"TORONTO STOCK EXCHANGE": "TSX", "TSX VENTURE EXCHANGE": "TSXV", "TSX-V": "TSXV", "CNSX": "CSE"}
    )
    return out


def fetch_tmx(timeout: int = 30) -> pd.DataFrame:
    rows = []
    errors = []
    # Le répertoire public TMX expose une route JSON par première lettre.
    # "instruments" permet aussi de conserver les catégories d'actions et unités.
    tasks = [
        (exchange_code, exchange_name, letter)
        for exchange_code, exchange_name in (("tsx", "TSX"), ("tsxv", "TSXV"))
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    ]

    def fetch_page(task):
        exchange_code, exchange_name, letter = task
        url = f"https://www.tsx.com/json/company-directory/search/{exchange_code}/{letter}"
        return exchange_name, letter, _get(url, timeout).json()

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_page, task): task for task in tasks}
        for future in as_completed(futures):
            try:
                exchange_name, letter, payload = future.result()
                for issuer in payload.get("results", []):
                    instruments = issuer.get("instruments") or [issuer]
                    for instrument in instruments:
                        symbol = instrument.get("symbol") or issuer.get("symbol")
                        if symbol:
                            rows.append({
                                "symbol": symbol,
                                "exchange": exchange_name,
                                "name": issuer.get("name") or instrument.get("name") or "",
                                "security_type": "",
                            })
            except Exception as exc:
                exchange_name, letter = futures[future][1], futures[future][2]
                errors.append(f"{exchange_name}-{letter}: {exc}")
    result = pd.DataFrame(rows)
    if len(result) < 100:
        raise RuntimeError("Échec du répertoire JSON TSX/TSXV: " + " | ".join(errors[-3:]))
    return result.drop_duplicates(["symbol", "exchange"])


def fetch_yahoo_exchange(exchange_name: str, timeout: int = 30) -> pd.DataFrame:
    del timeout  # yfinance gère sa propre session et ses délais réseau.
    exchange_code = {"TSX": "TOR", "TSXV": "VAN", "CSE": "CNQ", "NEO": "NEO"}[exchange_name]
    query = yf.EquityQuery("eq", ["exchange", exchange_code])
    rows = []
    offset = 0
    page_size = 250
    while True:
        response = yf.screen(query, offset=offset, size=page_size, sortField="ticker", sortAsc=True)
        quotes = response.get("quotes", [])
        for quote in quotes:
            symbol = quote.get("symbol", "")
            if symbol:
                rows.append({
                    "symbol": symbol,
                    "exchange": exchange_name,
                    "name": quote.get("longName") or quote.get("shortName") or "",
                    "security_type": quote.get("quoteType") or "EQUITY",
                })
        offset += len(quotes)
        total = int(response.get("total", offset))
        if not quotes or offset >= total or offset >= 10000:
            break
    result = pd.DataFrame(rows)
    if result.empty:
        raise RuntimeError(f"Aucun titre Yahoo détecté pour {exchange_name}")
    return result.drop_duplicates("symbol")


def _walk_json(value, rows: list[dict]) -> None:
    if isinstance(value, dict):
        lower = {str(k).lower(): v for k, v in value.items()}
        symbol = lower.get("symbol") or lower.get("ticker") or lower.get("stock_symbol")
        if symbol and isinstance(symbol, str) and 1 <= len(symbol) <= 15:
            rows.append(
                {
                    "symbol": symbol,
                    "exchange": "CSE",
                    "name": lower.get("name") or lower.get("title") or lower.get("company_name") or "",
                    "security_type": lower.get("security_type") or lower.get("type") or "",
                }
            )
        for child in value.values():
            _walk_json(child, rows)
    elif isinstance(value, list):
        for child in value:
            _walk_json(child, rows)


def fetch_cse(timeout: int = 30) -> pd.DataFrame:
    response = _get(CSE_DIRECTORY_PAGE, timeout)
    frames = []
    try:
        frames.extend(pd.read_html(io.StringIO(response.text)))
    except ValueError:
        pass
    standardized = [_standardize_frame(frame, "CSE") for frame in frames]
    result = pd.concat(standardized, ignore_index=True) if standardized else pd.DataFrame()

    rows: list[dict] = []
    soup = BeautifulSoup(response.text, "html.parser")
    for script in soup.find_all("script"):
        raw = script.string or script.get_text()
        raw = raw.strip()
        if not raw or raw[0] not in "[{":
            continue
        try:
            _walk_json(json.loads(raw), rows)
        except json.JSONDecodeError:
            continue
    if rows:
        result = pd.concat([result, pd.DataFrame(rows)], ignore_index=True)

    # Dernier recours pour les pages qui exposent les symboles dans les URL.
    regex_rows = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        match = re.search(r"/(?:listed-company|company)/[^/]*?([A-Z][A-Z0-9.-]{0,11})/?$", href)
        if match:
            regex_rows.append({"symbol": match.group(1), "exchange": "CSE", "name": anchor.get_text(" ", strip=True), "security_type": ""})
    if regex_rows:
        result = pd.concat([result, pd.DataFrame(regex_rows)], ignore_index=True)

    result = result[result["symbol"].astype(str).str.lower().ne("nan")] if not result.empty else result
    if len(result) < 25:
        raise RuntimeError("Aucun symbole CSE détecté sur le répertoire officiel")
    result["exchange"] = "CSE"
    return result


def _load_custom(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=["symbol", "exchange", "name", "security_type"])
    frame = pd.read_csv(path)
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "exchange", "name", "security_type"])
    standardized = _standardize_frame(frame)
    if "exchange" in frame.columns:
        standardized["exchange"] = frame["exchange"].fillna("").astype(str).str.upper()
    return standardized


def build_universe(root: Path, cfg: dict, timeout: int = 30) -> tuple[pd.DataFrame, dict]:
    requested = set(cfg["exchanges"])
    cache_path = root / "cache" / "universe_cache.csv"
    diagnostics = {"sources": [], "warnings": []}
    frames = []

    if requested.intersection({"TSX", "TSXV"}):
        try:
            tmx = fetch_tmx(timeout)
            frames.append(tmx[tmx["exchange"].isin(requested)])
            diagnostics["sources"].append("TMX officiel")
        except Exception as exc:
            diagnostics["warnings"].append(str(exc))
            LOGGER.warning("Source TMX indisponible: %s", exc)

    if "CSE" in requested:
        try:
            frames.append(fetch_cse(timeout))
            diagnostics["sources"].append("CSE officiel")
        except Exception as exc:
            diagnostics["warnings"].append(str(exc))
            LOGGER.warning("Source CSE indisponible: %s", exc)
            try:
                frames.append(fetch_yahoo_exchange("CSE", timeout))
                diagnostics["sources"].append("répertoire Yahoo — CSE")
            except Exception as yahoo_exc:
                diagnostics["warnings"].append(str(yahoo_exc))

    if "NEO" in requested:
        try:
            frames.append(fetch_yahoo_exchange("NEO", timeout))
            diagnostics["sources"].append("répertoire Yahoo — Cboe Canada/NEO")
        except Exception as exc:
            diagnostics["warnings"].append(str(exc))
            LOGGER.warning("Source NEO indisponible: %s", exc)

    if cfg.get("include_custom_csv", True):
        custom = _load_custom(root / "data" / "custom_symbols.csv")
        if not custom.empty:
            frames.append(custom)
            diagnostics["sources"].append("data/custom_symbols.csv")

    current = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    minimum = int(cfg.get("minimum_valid_symbols", 100))
    if len(current) < minimum and cache_path.exists():
        cached = pd.read_csv(cache_path)
        current = pd.concat([current, cached], ignore_index=True)
        diagnostics["sources"].append("cache de la dernière liste valide")
        diagnostics["warnings"].append("Univers officiel incomplet; fusion avec le cache")

    if current.empty:
        raise RuntimeError("Aucun univers canadien valide et aucun cache disponible")

    for column in ("symbol", "exchange", "name", "security_type"):
        if column not in current:
            current[column] = ""
        current[column] = current[column].fillna("").astype(str).str.strip()
    current["exchange"] = current["exchange"].str.upper()
    current = current[current["exchange"].isin(requested) | current["symbol"].str.contains(r"\.(TO|V|CN|NE)$", regex=True)]

    excluded = "|".join(re.escape(x) for x in cfg.get("exclude_keywords", []))
    if excluded:
        descriptor = (current["name"] + " " + current["security_type"]).str.upper()
        current = current[~descriptor.str.contains(excluded, regex=True, na=False)]

    current["yahoo_symbol"] = [yahoo_symbol(s, e) for s, e in zip(current["symbol"], current["exchange"])]
    current = current[current["yahoo_symbol"].str.match(r"^[A-Z0-9][A-Z0-9-]*\.(TO|V|CN|NE)$")]
    current = current.drop_duplicates("yahoo_symbol").sort_values(["exchange", "yahoo_symbol"]).reset_index(drop=True)
    if len(current) < minimum:
        raise RuntimeError(f"Univers trop petit ({len(current)} symboles); seuil de sécurité={minimum}")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    current.to_csv(cache_path, index=False)
    diagnostics["universe_size"] = len(current)
    diagnostics["by_exchange"] = current["exchange"].value_counts().to_dict()
    return current, diagnostics
