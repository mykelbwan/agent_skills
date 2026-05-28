# Pipeline Guide

The recorder has two collection paths.

## Transaction Scan

The transaction scanner walks each block in the requested range with `eth_getBlockByNumber`.
It filters transactions where:

- `to == target contract`
- and, when provided, `from == wallet`

This catches direct calls even if the contract emits no events.

## Log Scan

The log scanner calls `eth_getLogs` for the target contract and block range.
It collects emitted event logs and optionally narrows to logs whose indexed topics contain the wallet address.

This is faster than full transaction scanning, but it only sees emitted logs.

## Modes

- `transactions`: direct calls only
- `logs`: emitted logs only
- `combined`: both direct calls and logs

## Labels

The recorder ships with common labels:

- ERC20/ERC721 `Transfer`
- ERC20/ERC721 `Approval`
- common function selectors such as `approve`, `transfer`, `transferFrom`, `mint`, `claim`, `deposit`, `withdraw`, `stake`, `unstake`

Add project-specific labels in config:

```json
{
  "selectorLabels": {
    "0xabcdef12": "deposit(uint256,address)"
  },
  "eventLabels": {
    "0x1234...": "Deposited(address,uint256)"
  }
}
```

## Outputs

- `timeline.md`: human-readable sequence for screenshots or demos
- `timeline.json`: structured timeline for downstream agents
- `transactions.csv`: direct call rows
- `events.csv`: log rows
- `summary.json`: counts and config echo

## Recommended Demo

Deploy a small Foundry or Hardhat test contract on Atlantic testnet, call `setNumber` and `increment`,
then run this recorder over the deployment block range. The timeline should show direct calls to the
contract and any emitted logs if the test contract emits events.
