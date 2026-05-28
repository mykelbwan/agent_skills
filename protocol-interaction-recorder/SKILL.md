---
name: protocol-interaction-recorder
description: >
  Use this skill when a user wants to reconstruct a wallet or protocol interaction timeline
  on Pharos. It scans bounded block ranges on Pharos Atlantic testnet or mainnet, finds
  transactions sent to a target contract, collects emitted logs from that contract, labels
  known function selectors and event topics, and exports a readable timeline plus JSON/CSV
  reports. This is useful for explaining protocol usage such as approve, deposit, mint,
  claim, withdraw, vote, stake, unstake, or other contract interactions without manually
  checking a block explorer.
version: 0.1.0
---

# Protocol Interaction Recorder

This skill records what happened between a wallet and a target protocol contract on Pharos.
It is designed for bounded investigations: support tickets, demo traces, protocol QA, user
onboarding, and campaign analytics.

## Default Network

Unless the user explicitly asks for mainnet, use Pharos Atlantic testnet.

- RPC URL: `https://atlantic.dplabs-internal.com`
- Chain ID: `688689`
- Explorer: `https://atlantic.pharosscan.xyz/`
- Native token: `PHRS`

## What It Does

- Scans blocks for direct transactions sent to a target contract.
- Optionally filters those transactions by wallet address.
- Scans logs emitted by the target contract.
- Labels common ERC20/ERC721 selectors and events.
- Accepts custom selector and event-topic labels from config.
- Exports:
  - `timeline.md`
  - `timeline.json`
  - `transactions.csv`
  - `events.csv`
  - `summary.json`

## When To Use

Use prompts like:

- `Record what this wallet did with my staking contract over the last 5000 blocks`
- `Explain all interactions with this protocol contract on Atlantic testnet`
- `Build a timeline for this user's deposits and withdrawals`
- `Summarize protocol events emitted by this contract`

## Run Commands

Deterministic demo without live RPC:

```bash
python3 main.py record \
  --config assets/demo-fixture.json \
  --output-dir out/demo-fixture
```

Then inspect:

```bash
cat out/demo-fixture/summary.json
cat out/demo-fixture/timeline.md
cat out/demo-fixture/transactions.csv
cat out/demo-fixture/events.csv
```

Create or edit a config from `assets/example-config.json`, then run:

```bash
python3 main.py record \
  --config assets/example-config.json \
  --output-dir out/protocol-recorder-demo
```

Direct CLI usage:

```bash
python3 main.py record \
  --contract 0x0000000000000000000000000000000000000000 \
  --wallet 0x0000000000000000000000000000000000000000 \
  --from-block 1 \
  --to-block latest \
  --output-dir out/protocol-recorder-demo
```

## Practical Limits

- Always use a bounded block range for demos and production use.
- `transactions` mode scans full blocks and is heavier than `logs` mode.
- Some contract calls emit no logs; use `combined` mode when you need both direct calls and events.
- Decoding is label-based in this first version. For unknown selectors/topics, the output keeps raw calldata and topic values.

## Safety

- This skill is read-only.
- It does not require a private key.
- It never sends transactions.
