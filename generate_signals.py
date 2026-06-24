#!/usr/bin/env python3
"""Generate validated long-only Nifty signals from OHLCV CSV data.

Signal convention:
  1  = enter long
  0  = no action / hold current state
 -1  = exit long

The validator enforces a long-only state machine:
  - no -1 signal while flat
  - no 1 signal while already long
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "Nifty 50 Historical Data (1).csv"
DEFAULT_OUTPUT = SCRIPT_DIR / "nifty_long_only_signals.csv"
DEFAULT_SUMMARY = SCRIPT_DIR / "signal_summary.json"


@dataclass
class Bar:
    date: datetime
    date_text: str
    close: float
    open: float
    high: float
    low: float
    volume: float | None


def parse_number(value: str) -> float:
    return float(value.replace(",", "").strip())


def parse_volume(value: str) -> float | None:
    value = value.strip().replace(",", "")
    if not value or value == "-":
        return None

    multiplier = 1.0
    suffix = value[-1].upper()
    if suffix == "K":
        multiplier = 1_000.0
        value = value[:-1]
    elif suffix == "M":
        multiplier = 1_000_000.0
        value = value[:-1]
    elif suffix == "B":
        multiplier = 1_000_000_000.0
        value = value[:-1]

    return float(value) * multiplier


def load_bars(path: Path) -> list[Bar]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        bars = []
        for row in reader:
            date = datetime.strptime(row["Date"], "%d-%m-%Y")
            bars.append(
                Bar(
                    date=date,
                    date_text=date.strftime("%Y-%m-%d"),
                    close=parse_number(row["Price"]),
                    open=parse_number(row["Open"]),
                    high=parse_number(row["High"]),
                    low=parse_number(row["Low"]),
                    volume=parse_volume(row.get("Vol.", "")),
                )
            )

    return sorted(bars, key=lambda bar: bar.date)


def ema(values: list[float], span: int) -> list[float | None]:
    if span <= 0:
        raise ValueError("EMA span must be positive")

    result: list[float | None] = [None] * len(values)
    if len(values) < span:
        return result

    alpha = 2.0 / (span + 1.0)
    current = sum(values[:span]) / span
    result[span - 1] = current

    for idx in range(span, len(values)):
        current = (values[idx] * alpha) + (current * (1.0 - alpha))
        result[idx] = current

    return result


def sma(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if window <= 0:
        raise ValueError("SMA window must be positive")

    rolling_sum = 0.0
    for idx, value in enumerate(values):
        rolling_sum += value
        if idx >= window:
            rolling_sum -= values[idx - window]
        if idx >= window - 1:
            result[idx] = rolling_sum / window

    return result


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if period <= 0:
        raise ValueError("RSI period must be positive")
    if len(values) <= period:
        return result

    gains: list[float] = []
    losses: list[float] = []
    for idx in range(1, period + 1):
        change = values[idx] - values[idx - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    result[period] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))

    for idx in range(period + 1, len(values)):
        change = values[idx] - values[idx - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        result[idx] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))

    return result


def generate_raw_signals(bars: list[Bar]) -> list[int]:
    closes = [bar.close for bar in bars]
    fast_ema = ema(closes, 12)
    slow_ema = ema(closes, 26)
    trend_sma = sma(closes, 50)
    momentum_rsi = rsi(closes, 14)

    raw_signals = [0] * len(bars)
    for idx in range(1, len(bars)):
        if None in (
            fast_ema[idx - 1],
            fast_ema[idx],
            slow_ema[idx - 1],
            slow_ema[idx],
            trend_sma[idx],
            momentum_rsi[idx],
        ):
            continue

        bullish_cross = fast_ema[idx - 1] <= slow_ema[idx - 1] and fast_ema[idx] > slow_ema[idx]
        bearish_cross = fast_ema[idx - 1] >= slow_ema[idx - 1] and fast_ema[idx] < slow_ema[idx]
        above_trend = closes[idx] > trend_sma[idx]
        positive_momentum = momentum_rsi[idx] >= 52.0
        weak_momentum = momentum_rsi[idx] <= 45.0
        below_trend = closes[idx] < trend_sma[idx]

        if bullish_cross and above_trend and positive_momentum:
            raw_signals[idx] = 1
        elif bearish_cross or weak_momentum or below_trend:
            raw_signals[idx] = -1

    return raw_signals


def validate_long_only(raw_signals: Iterable[int]) -> tuple[list[int], dict[str, int]]:
    position = 0
    cleaned: list[int] = []
    stats = {
        "suppressed_invalid_exits": 0,
        "suppressed_duplicate_entries": 0,
        "entries": 0,
        "exits": 0,
    }

    for signal in raw_signals:
        if signal == 1:
            if position == 0:
                cleaned.append(1)
                position = 1
                stats["entries"] += 1
            else:
                cleaned.append(0)
                stats["suppressed_duplicate_entries"] += 1
        elif signal == -1:
            if position == 1:
                cleaned.append(-1)
                position = 0
                stats["exits"] += 1
            else:
                cleaned.append(0)
                stats["suppressed_invalid_exits"] += 1
        elif signal == 0:
            cleaned.append(0)
        else:
            raise ValueError(f"Unexpected signal value: {signal}")

    stats["ending_position"] = position
    return cleaned, stats


def assert_long_only(signals: Iterable[int]) -> None:
    position = 0
    for row_number, signal in enumerate(signals, start=1):
        if signal == 1:
            if position == 1:
                raise AssertionError(f"Duplicate long entry at output row {row_number}")
            position = 1
        elif signal == -1:
            if position == 0:
                raise AssertionError(f"Exit while flat at output row {row_number}")
            position = 0
        elif signal != 0:
            raise AssertionError(f"Invalid signal at output row {row_number}: {signal}")


def write_signals(path: Path, bars: list[Bar], signals: list[int]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Date", "Signal"])
        writer.writeheader()
        for bar, signal in zip(bars, signals):
            writer.writerow({"Date": bar.date_text, "Signal": signal})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate validated long-only Nifty signals from local OHLCV data."
    )
    parser.add_argument("--input", default=DEFAULT_INPUT, type=Path)
    parser.add_argument("--output", default=DEFAULT_OUTPUT, type=Path)
    parser.add_argument("--summary", default=DEFAULT_SUMMARY, type=Path)
    args = parser.parse_args()

    input_path = args.input.resolve()
    output_path = args.output.resolve()
    summary_path = args.summary.resolve()

    bars = load_bars(input_path)
    raw_signals = generate_raw_signals(bars)
    signals, validation_stats = validate_long_only(raw_signals)
    assert_long_only(signals)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    write_signals(output_path, bars, signals)

    summary = {
        "input_file": str(input_path),
        "output_file": str(output_path),
        "rows": len(bars),
        "first_date": bars[0].date_text if bars else None,
        "last_date": bars[-1].date_text if bars else None,
        "strategy": "Long-only 12/26 EMA bullish cross with 50-SMA trend and RSI momentum filter; exits on bearish cross, RSI weakness, or close below 50-SMA.",
        "validation": validation_stats,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
