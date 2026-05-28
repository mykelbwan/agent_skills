# Protocol Interaction Recorder

Protocol Interaction Recorder is a Pharos Agent Center skill for reconstructing what happened between a wallet and a smart contract.

It scans bounded block ranges, finds direct transactions to a target contract, collects emitted logs, labels known function selectors and event topics, and exports a readable timeline plus JSON and CSV reports.

## What It Does

- Scans direct transactions sent to a target contract.
- Optionally filters activity by wallet address.
- Scans logs emitted by the target contract.
- Labels common function selectors such as `approve`, `transfer`, `mint`, `stake`, `deposit`, `withdraw`, `claim`, and `increment`.
- Accepts custom selector and event labels from config.
- Exports `timeline.md`, `timeline.json`, `transactions.csv`, `events.csv`, and `summary.json`.
- Includes fixture mode for deterministic demos and offline testing.

## Why This Is Useful

Developers, support teams, and protocol operators often need to answer questions like:

- What did this wallet do with my contract?
- Did a user actually deposit, stake, claim, or withdraw?
- Which transaction emitted this event?
- Can I get a clean timeline without manually clicking through a block explorer?

This skill turns that investigation into one repeatable command.

## Folder Layout

```text
protocol-interaction-recorder/
  SKILL.md
  README.md
  main.py
  assets/
    demo-fixture.json
    example-config.json
  references/
    pipeline-guide.md
```

## Requirements

- Python 3.9+
- Internet/RPC access for live Pharos scans
- A bounded block range for production use
- A target contract address

No private key is required. This skill is read-only and never sends transactions.

## Quick Demo

Run a deterministic offline demo:

```bash
cd /path/to/repo

python3 protocol-interaction-recorder/main.py record \
  --config protocol-interaction-recorder/assets/demo-fixture.json \
  --output-dir protocol-interaction-recorder/out/demo-fixture
```

Inspect the generated reports:

```bash
cat protocol-interaction-recorder/out/demo-fixture/summary.json
cat protocol-interaction-recorder/out/demo-fixture/timeline.md
cat protocol-interaction-recorder/out/demo-fixture/transactions.csv
cat protocol-interaction-recorder/out/demo-fixture/events.csv
```

Expected demo result:

- 2 matching wallet transactions
- 2 matching emitted events
- 4 timeline items

The fixture includes another wallet's transaction and event too, but the config filters to one wallet so the output demonstrates wallet-scoped investigation.

## Live Pharos Scan

Edit `assets/example-config.json` with a real contract address, wallet address if needed, and a bounded block range. Then run:

```bash
python3 protocol-interaction-recorder/main.py record \
  --config protocol-interaction-recorder/assets/example-config.json \
  --output-dir protocol-interaction-recorder/out/live-scan
```

You can also pass values directly:

```bash
python3 protocol-interaction-recorder/main.py record \
  --contract 0x0000000000000000000000000000000000000000 \
  --wallet 0x0000000000000000000000000000000000000000 \
  --from-block 22800000 \
  --to-block 22800500 \
  --mode combined \
  --output-dir protocol-interaction-recorder/out/live-scan
```

## Modes

- `transactions`: scans direct contract calls by reading full blocks.
- `logs`: scans emitted contract logs with `eth_getLogs`.
- `combined`: records both calls and events into one timeline.

`combined` is the default and is best for investigations.

## Custom Labels

Add labels in the config:

```json
{
  "selectorLabels": {
    "0xd09de08a": "increment()"
  },
  "eventLabels": {
    "0x...": "Deposit(address,uint256)"
  }
}
```

Or pass them through the CLI:

```bash
--selector-label 0xd09de08a=increment()
--event-label 0xabc...=Deposit(address,uint256)
```

## Fixture Mode

`assets/demo-fixture.json` includes mock transactions and logs. When a config contains a `fixture` object, the skill skips live RPC calls and uses the supplied data while running the same filtering, labeling, timeline, and report-writing logic.

This is useful for:

- demo recordings
- tests
- reviewer-friendly validation
- explaining how wallet filtering works

## Safety

- This skill never sends transactions.
- This skill does not need a private key.
- Always use bounded block ranges for live scans.
- Transaction scanning reads full blocks and can be heavier than log scanning.
