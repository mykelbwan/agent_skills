# Config Reference

The analytics script reads a single JSON config file.

## Top-Level Fields

```json
{
  "rpcUrl": "https://atlantic.dplabs-internal.com",
  "contractAddress": "0x...",
  "fromBlock": 0,
  "toBlock": "latest",
  "blockChunkSize": 2000,
  "maxBlockSpan": 100000,
  "requestChunkSize": 100,
  "interactionCountMode": "unique_logs",
  "eventFilter": {
    "topic0": "0x...",
    "topics": ["0x...", null, null, null]
  },
  "addressSources": [
    { "type": "topic", "index": 1, "label": "from" },
    { "type": "topic", "index": 2, "label": "to" },
    { "type": "data",  "offset": 12, "label": "recipient_from_calldata" }
  ],
  "qualification": {
    "minInteractions": 2,
    "balanceCheck": {
      "type": "native",
      "minBalanceWei": "10000000000000000"
    }
  },
  "airdrop": {
    "amountWei": "100000000000000000",
    "tiered": [
      { "minInteractions": 10, "amountWei": "200000000000000000" },
      { "minInteractions": 5,  "amountWei": "150000000000000000" }
    ]
  },
  "excludeAddresses": [
    "0x0000000000000000000000000000000000000000"
  ]
}
```

## Event Filter Rules

Use either:

- `eventFilter.topic0` for a simple single-event filter, or
- `eventFilter.topics` for a full `eth_getLogs` topics array

Examples:

- ERC20 `Transfer(address,address,uint256)` topic0:
  `0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef`
- Custom `Mint(address,uint256)` topic0:
  use the keccak256 event signature hash for that event

## Address Source Rules

Two source types are supported:

### `type: "topic"` (indexed event arguments)

```json
{ "type": "topic", "index": 2, "label": "recipient" }
```

- `index` is the position in the topics array (0 = event signature, 1 = first indexed arg, etc.)

### `type: "data"` (non-indexed / calldata arguments)

```json
{ "type": "data", "offset": 12, "label": "recipient_from_data" }
```

- `offset` is the byte position of the address within the `data` field.
- ABI-encoded addresses start at byte 12 (the first 12 bytes of a 32-byte slot are padding).
- For the second ABI-encoded argument, use `offset: 44` (32 + 12).

## Qualification Rules

`interactionCountMode`

- `unique_logs` counts a wallet once per log, even if it appears in multiple configured sources in that log.
- `source_hits` counts every configured source appearance. Use this only when double-counting sender/recipient appearances is intentional.

`minInteractions` — minimum interaction count after applying `interactionCountMode`.

`balanceCheck.type`

- `native` checks `eth_getBalance`
- `erc20` checks `balanceOf(address)` via `eth_call`

ERC20 balance config:

```json
{
  "type": "erc20",
  "tokenAddress": "0x...",
  "minBalanceWei": "5000000000000000000"
}
```

## Tiered Airdrop Amounts

Reward more active wallets with larger drops. Tiers are evaluated highest-first;
the first matching tier wins. Falls back to `airdrop.amountWei` if no tier matches.

```json
"airdrop": {
  "amountWei": "100000000000000000",
  "tiered": [
    { "minInteractions": 10, "amountWei": "200000000000000000" },
    { "minInteractions": 5,  "amountWei": "150000000000000000" }
  ]
}
```

## CLI Flags

```bash
# Standard run
python3 intelligent_airdrop_filter.py --config config.json --output-dir ./out

# Scan logs only, skip balance checks (fast preview)
python3 intelligent_airdrop_filter.py --config config.json --output-dir ./out --dry-run

# Enable verbose/debug logging
python3 intelligent_airdrop_filter.py --config config.json --output-dir ./out --verbose
```

## Fixture Demo Mode

For recording or offline validation, a config can include a `fixture` object. When present, the
script skips live RPC calls and uses the supplied logs and balances while running the same
aggregation, qualification, and report-writing logic.

```json
{
  "rpcUrl": "fixture://deterministic-demo",
  "fixture": {
    "latestBlock": 110,
    "balances": {
      "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": "50000000000000000"
    },
    "logs": []
  }
}
```

Run:

```bash
python3 intelligent_airdrop_filter.py --config assets/demo-fixture.json --output-dir out/demo-fixture
```

## Output Files

- `summary.json`: aggregate counts, qualification params, and file paths
- `qualified.csv`: airdrop-ready `address,amount` file (compatible with Pharos BatchAirdrop.s.sol)
- `qualified.txt`: plain address list
- `disqualified.csv`: failed addresses with reason and human-readable balance display

## Prompt Pattern

Use this skill with prompts like:

`Scan this Pharos testnet contract for wallets that interacted at least 3 times, require at least 0.05 PHRS balance, and export a CSV for a tiered airdrop — 2 PHRS for 5+ interactions, 1 PHRS for everyone else.`

## Range Safety

The script rejects scans larger than `maxBlockSpan` to avoid accidental full-history RPC scans.
Set a bounded `fromBlock` and `toBlock` for demos. Increase `maxBlockSpan` only when you are
sure the RPC endpoint can handle the requested range.
