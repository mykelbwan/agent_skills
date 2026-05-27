# Pipeline Guide

This skill provides a resumable Pharos deployment pipeline for local smart contract projects.

## What It Detects

- Foundry projects: `foundry.toml`, `src/`, `out/`, `broadcast/`
- Hardhat projects: `hardhat.config.*`, `contracts/`, `artifacts/`
- Solidity sources from common directories
- ABI and bytecode from compiled artifacts when available

## Pipeline Stages

- `scanned`
- `compiled`
- `gas_estimated`
- `deployed`
- `verified`
- `synced`
- `smoke_tested`

Each stage writes to `config/devops-cache.json`.
Only successfully executed stages are marked complete.

## Resume Model

`resume --workspace <path>` reads the cached run for that workspace and continues from the next incomplete stage.

Examples:

- deploy succeeded, verify failed:
  resume starts at verify
- verify succeeded, env sync failed:
  resume starts at sync
- sync succeeded, smoke test was skipped:
  resume can run smoke test if requested

## Supported Operations

### Scan

Discovers candidate contracts and tries to infer the target contract from:

- explicit `--contract`
- natural-language intent match
- common role names like token, staking, vesting, vault

### Compile

- Foundry: `forge build`
- Hardhat: `npx hardhat compile`

### Deploy

For Foundry projects, deployment uses `forge create`:

- executes `forge create <source.sol:Contract> --rpc-url ... --private-key $PRIVATE_KEY`
- passes constructor arguments through `--constructor-args`
- avoids requiring a generated deployment script or `forge-std`

For Hardhat projects, the current implementation supports end-to-end execution for official viem-based and ethers-based setups:

- compile with `hardhat compile`
- generate a temporary deployment script in `scripts/`
- execute it through `hardhat run`
- use `hardhat verify` when the `hardhat-verify` plugin and Pharos network/explorer config are present

The viem path follows the official Hardhat viem plugin pattern:

- install `@nomicfoundation/hardhat-viem` or the viem toolbox
- use `const { viem } = await hre.network.connect()`
- deploy with `viem.deployContract(...)`
- interact with deployed contracts using `viem.getContractAt(...)`

### Verify

Uses `forge verify-contract` with Pharos Atlantic testnet settings.

For Hardhat 3, official verification is done with `@nomicfoundation/hardhat-verify`.
Per the Hardhat docs:

- `hardhat-verify` supports Etherscan, Blockscout, and Sourcify
- Blockscout does not need an API key
- custom networks need matching explorer metadata in Hardhat config

### Sync

Updates local files by key replacement or append:

- existing `.env`
- existing `.env.local`
- frontend env keys like `NEXT_PUBLIC_*`
- optional custom paths

Use `--create-missing-env` if the skill should create missing env files.

### Smoke Test

Supports:

- read call plans
- write transaction plans
- optional value
- optional expectation label

## Failure Handling

- Missing `forge` or `cast`: pipeline stays in plan mode and records required commands
- Missing `PRIVATE_KEY`: deployment and smoke-test execution are blocked
- Missing artifact bytecode: compile first, then retry artifact resolution
- Verification delay: wait after deployment before verify, then retry

## Current Scope

- Foundry: scan, compile, gas estimate, deploy, verify, resume, env sync, smoke-test support
- Hardhat: scan, compile, deploy, env sync, smoke-test support for viem-based and ethers-based Hardhat workspaces
- Hardhat verification: supported when `@nomicfoundation/hardhat-verify` is installed and the Pharos chain/network is configured in Hardhat
- Resume state: stored per workspace inside `config/devops-cache.json`

## Recommended Demo Prompt

`Deploy and test my local VestingVault contract on Pharos Atlantic testnet, verify it, update NEXT_PUBLIC_VESTING_VAULT_ADDRESS, and save enough state so I can resume if verification fails.`
