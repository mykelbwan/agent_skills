# Intelligent Airdrop Filter

Intelligent Airdrop Filter is a Pharos Agent Center skill for building airdrop recipient lists from onchain activity instead of manually exporting logs, cleaning spreadsheets, and guessing eligibility.

It scans contract event logs, extracts wallet addresses from configured event topics or data fields, counts interactions, checks native or ERC20 balances in batches, and exports airdrop-ready files.

## What It Does

- Fetches historical logs from a target contract with `eth_getLogs`.
- Extracts participant wallets from indexed topics or ABI-encoded data.
- Aggregates interaction counts per wallet.
- Filters wallets by minimum interaction count.
- Checks native `PHRS` balances or ERC20 `balanceOf` balances.
- Supports tiered airdrop amounts based on activity.
- Exports `qualified.csv`, `qualified.txt`, `disqualified.csv`, and `summary.json`.
- Includes fixture mode for deterministic demos and offline testing.

## Why This Is Useful

Airdrop filtering is usually a messy pipeline: query logs, export CSV, deduplicate wallets, check balances, remove ineligible addresses, and format the final recipient file. This skill turns that into one repeatable command that an agent can run and explain.

The output `qualified.csv` uses this format:

```csv
address,amount
0x...,100000000000000000
```

That file can be passed to a batch airdrop flow or reviewed before execution.

## Folder Layout

```text
intelligent-airdrop-filter/
  SKILL.md
  README.md
  assets/
    demo-fixture.json
    example-native.json
    example-erc20.json
  references/
    config.md
  scripts/
    intelligent_airdrop_filter.py
```

## Requirements

- Python 3.9+
- Internet/RPC access for live scans
- A bounded block range for production use
- A target contract address and event layout

No private key is required. This skill only analyzes data and writes local reports. It does not broadcast transactions.

## Quick Demo

Run a deterministic offline demo:

```bash
cd /path/to/repo

python3 intelligent-airdrop-filter/scripts/intelligent_airdrop_filter.py \
  --config intelligent-airdrop-filter/assets/demo-fixture.json \
  --output-dir intelligent-airdrop-filter/out/demo-fixture
```

Inspect the generated reports:

```bash
cat intelligent-airdrop-filter/out/demo-fixture/summary.json
cat intelligent-airdrop-filter/out/demo-fixture/qualified.csv
cat intelligent-airdrop-filter/out/demo-fixture/disqualified.csv
```

Expected demo result:

- 10 matched logs
- 4 unique addresses
- 2 qualified wallets
- 2 disqualified wallets

## Live Native Balance Scan

Edit `assets/example-native.json` with your target contract, event topic, address source, and block range. Then run:

```bash
python3 intelligent-airdrop-filter/scripts/intelligent_airdrop_filter.py \
  --config intelligent-airdrop-filter/assets/example-native.json \
  --output-dir intelligent-airdrop-filter/out/native-scan
```

## Live ERC20 Balance Scan

Edit `assets/example-erc20.json` with your target contract, ERC20 token address, event topic, address source, and block range. Then run:

```bash
python3 intelligent-airdrop-filter/scripts/intelligent_airdrop_filter.py \
  --config intelligent-airdrop-filter/assets/example-erc20.json \
  --output-dir intelligent-airdrop-filter/out/erc20-scan
```

## Dry Run

Use `--dry-run` to scan logs and count unique addresses without checking balances or writing reports:

```bash
python3 intelligent-airdrop-filter/scripts/intelligent_airdrop_filter.py \
  --config intelligent-airdrop-filter/assets/example-native.json \
  --output-dir intelligent-airdrop-filter/out/native-preview \
  --dry-run
```

## Configuration

The config controls:

- RPC URL
- target contract
- block range
- event topic filter
- wallet address extraction sources
- minimum interaction count
- native or ERC20 balance threshold
- flat or tiered airdrop amounts
- excluded addresses

Read `references/config.md` for the full config reference.

## Fixture Mode

`assets/demo-fixture.json` includes mock logs and balances. When a config contains a `fixture` object, the script skips RPC calls and uses the fixture data while running the same aggregation, qualification, and report-writing logic.

This is useful for:

- demo recordings
- tests
- judging/review without needing live Pharos event history
- explaining exactly why each wallet qualified or failed

## Safety

- This skill never sends transactions.
- This skill does not need a private key.
- Always use bounded block ranges for live RPC scans.
- Review `qualified.csv` before using it for a real airdrop.
- Keep treasury, deployer, zero, and system addresses in `excludeAddresses` when needed.
