# Nifty Long-Only Trading Signal Strategy

This repository contains a Python implementation of a long-only indicator strategy for Nifty OHLCV data. It generates date-wise trading action signals in CSV format:

- `1` = enter long
- `0` = no action / hold current state
- `-1` = exit long

The strategy is long-only. It does not allow short selling or duplicate long entries.

## Strategy Logic

The script uses the following indicators:

- 12-period EMA
- 26-period EMA
- 50-period SMA
- 14-period RSI

Entry signal:

- 12 EMA crosses above 26 EMA
- Close price is above 50 SMA
- RSI is at least 52

Exit signal:

- 12 EMA crosses below 26 EMA, or
- RSI falls to 45 or below, or
- Close price falls below 50 SMA

## Long-Only Validation

After raw signals are generated, the script applies a position-state validator:

- If current position is flat, `-1` is replaced with `0`
- If current position is already long, another `1` is replaced with `0`
- The cumulative position is always restricted to `0` or `1`

This ensures:

- No sell signal appears before a buy signal
- No new buy signal appears while already invested
- No short position can be created

## Input Format

Expected CSV columns:

```csv
Date,Price,Open,High,Low,Vol.,Change %
```

The included parser supports dates in `dd-mm-yyyy` format and prices containing commas.

## Run

Place the input CSV in this same folder. The submitted folder already includes:

```text
Nifty 50 Historical Data (1).csv
```

Then run:

```bash
python3 generate_signals.py
```

By default, the script reads:

```text
Nifty 50 Historical Data (1).csv
```

and writes the output in the same folder:

```text
nifty_long_only_signals.csv
```

You can also pass custom file paths:

```bash
python3 generate_signals.py \
  --input "Nifty 50 Historical Data (1).csv" \
  --output nifty_long_only_signals.csv \
  --summary signal_summary.json
```

## Output Format

The generated CSV contains:

```csv
Date,Signal
2016-01-01,0
2016-01-04,0
...
```

## Files

- `generate_signals.py` - strategy and validation code
- `Nifty 50 Historical Data (1).csv` - input data
- `nifty_long_only_signals.csv` - generated signal output
- `signal_summary.json` - run summary and validation counts
- `requirements.txt` - dependency note

## Notes

The provided data file is daily OHLCV data. If intraday data is supplied with the same OHLCV structure and timestamp column, the same strategy framework can be adapted for intraday signal generation.
