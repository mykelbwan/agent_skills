---
name: intelligent-airdrop-filter
description: >
  Use this skill when a user wants to build an airdrop allowlist from onchain activity on
  Pharos, filter wallets by historic contract interactions, enforce minimum interaction and
  balance thresholds, and export a CSV that can be executed through the Pharos batch airdrop
  flow on Atlantic testnet. This skill scans logs from a target contract, aggregates unique
  addresses from event topics, checks native or ERC20 balances in batches, produces qualified
  and disqualified reports, and prepares airdrop-ready recipient files.
version: 0.1.0
---

# Intelligent Airdrop Filter

This skill builds an analytics-driven airdrop recipient list from historical contract events on
Pharos Atlantic testnet, then exports a CSV that can be fed into the batch airdrop flow from the
Pharos skill engine.

## When To Use

Use this skill when the user wants to:

- Find all wallets that interacted with a contract on Pharos
- Build an airdrop allowlist from `Transfer`, `Mint`, or custom event logs
- Require `InteractionCount >= X`
- Require a minimum native token balance or ERC20 token balance
- Export eligible wallets to a CSV for the Pharos airdrop scripts

## Default Network

Default to the Pharos Atlantic testnet unless the user explicitly overrides it.

- RPC URL: `https://atlantic.dplabs-internal.com`
- Chain ID: `688689`
- Explorer: `https://atlantic.pharosscan.xyz/`
- Native token: `PHRS`

## Workflow

1. Prepare a config JSON from one of the examples in `assets/`.
2. Run `scripts/intelligent_airdrop_filter.py` with that config.
3. Review the generated outputs:
   - `summary.json`
   - `qualified.csv`
   - `qualified.txt`
   - `disqualified.csv`
4. If the output looks correct, feed `qualified.csv` into the Pharos multi-batch airdrop flow.

## Inputs Required

The skill needs:

- A target contract address
- A block range to scan
- The event topic hash to filter on, if you want a specific event
- The topic indexes that contain wallet addresses
- A minimum interaction count
- A balance rule:
  - native balance threshold, or
  - ERC20 token balance threshold
- An airdrop amount in wei for CSV export

Read `references/config.md` before editing the config if the event layout is custom.

## Run Command

Deterministic demo without live RPC:

```bash
python3 scripts/intelligent_airdrop_filter.py \
  --config assets/demo-fixture.json \
  --output-dir out/demo-fixture
```

Then inspect:

```bash
cat out/demo-fixture/summary.json
cat out/demo-fixture/qualified.csv
cat out/demo-fixture/disqualified.csv
```

Live RPC scan:

```bash
python3 scripts/intelligent_airdrop_filter.py \
  --config assets/example-native.json \
  --output-dir out/native-demo
```

ERC20 qualification example:

```bash
python3 scripts/intelligent_airdrop_filter.py \
  --config assets/example-erc20.json \
  --output-dir out/erc20-demo
```

## Output Contract Handoff

The generated `qualified.csv` is compatible with the Pharos batch airdrop pattern:

- `address,amount`
- one recipient per line
- amount stored in wei

For large recipient sets, place `qualified.csv` in the project root as `airdrop.csv` and then use
the Pharos multi-batch airdrop scripts from `pharos-skill-engine-0.1.0/assets/airdrop/`.

Reference execution pattern:

```bash
CSV_PATH=airdrop.csv BATCH_SIZE=200 \
  forge script assets/airdrop/BatchAirdrop.s.sol:BatchAirdrop \
  --rpc-url https://atlantic.dplabs-internal.com \
  --private-key $PRIVATE_KEY \
  --broadcast
```

For ERC20 payouts:

```bash
CSV_PATH=airdrop.csv BATCH_SIZE=200 TOKEN_ADDRESS=<token_address> \
  forge script assets/airdrop/BatchAirdropERC20.s.sol:BatchAirdropERC20 \
  --rpc-url https://atlantic.dplabs-internal.com \
  --private-key $PRIVATE_KEY \
  --broadcast
```

## Practical Notes

- Use a bounded block range. Large full-history scans may be slow or rate-limited.
- The script enforces `maxBlockSpan` so placeholder/demo configs do not accidentally scan the full chain.
- Prefer JSON-RPC batching for balance checks. This skill does that automatically.
- If a contract emits multiple participant addresses per event, include all relevant topic indexes.
- Use `interactionCountMode: "unique_logs"` for eligibility fairness; use `"source_hits"` only when each address appearance should count separately.
- Exclude the zero address and known treasury/system addresses through the config file.

## Safety

- This skill only analyzes addresses and prepares output files.
- It does not broadcast transactions.
- Actual airdrop execution should be confirmed separately with the Pharos airdrop scripts.
