---
name: ai-devops-engineer
description: >
  Use this skill when a user wants an AI-assisted DevOps workflow for smart contracts:
  scan the active workspace for Foundry or Hardhat projects, infer the target contract from
  natural language, compile locally, estimate deployment gas, deploy to Pharos Atlantic
  testnet, verify on PharosScan, sync deployed addresses back into local env/config files,
  and optionally run a post-deployment smoke test. Foundry is supported directly, and
  Hardhat is supported end-to-end for viem-based or ethers-based Hardhat workspaces with
  the required official plugins and network configuration. This skill also supports workspace-scoped resumable
  execution through a local devops cache so the user can continue after failed compile,
  deploy, verify, sync, or smoke-test steps.
version: 0.1.0
---

# AI DevOps Engineer

This skill turns contract deployment and post-deployment wiring into a single conversational
pipeline for smart contract projects targeting Pharos.

## Use Cases

Use this skill when the user says things like:

- `Deploy my main token`
- `Deploy and verify my staking contract`
- `Resume the last Pharos deployment`
- `Deploy this contract and update my frontend env`
- `Deploy and run a smoke test`

## Default Network

Unless the user explicitly requests otherwise, use Pharos Atlantic testnet.

- RPC URL: `https://atlantic.dplabs-internal.com`
- Chain ID: `688689`
- Explorer: `https://atlantic.pharosscan.xyz/`
- Explorer API: `https://api.socialscan.io/pharos-atlantic-testnet`
- Native token: `PHRS`

## Folder Layout

This skill is self-contained:

- `main.py`: orchestration engine
- `config/devops-cache.json`: resumable pipeline state
- `references/pipeline-guide.md`: recovery and usage guide

## Core Workflow

1. Scan the workspace for Foundry or Hardhat projects.
2. Infer the target contract from the user's prompt or a direct contract name.
3. Inspect compiled artifacts when present to recover ABI, bytecode, and constructor metadata.
4. Compile the project.
5. Build a deployment plan for Atlantic testnet.
6. Optionally execute deploy and verification commands.
7. Optionally sync the deployed address back into existing local `.env` or app config files.
8. Optionally run a smoke test call or write transaction.
9. Save every step into `config/devops-cache.json` so `resume` can continue cleanly.

If the user does not provide an env key, derive one from the selected contract name. For example,
`Counter` becomes `COUNTER_ADDRESS` and `StakingVault` becomes
`STAKING_VAULT_ADDRESS`. Allow explicit `--sync-env-key` values to override this
default, and allow `--no-auto-sync-env` when the user does not want local env writes.

## Safety Rules

- Never expose the private key in logs or saved state.
- Default to planning mode unless the user explicitly wants execution.
- For actual write operations, confirm the deployer address and target network first.
- Use the workspace's native toolchain when possible: Foundry for Foundry projects, Hardhat for viem-based or ethers-based Hardhat projects.
- Hardhat viem support requires `@nomicfoundation/hardhat-viem` or the viem Hardhat toolbox.
- Hardhat verification requires `@nomicfoundation/hardhat-verify` and Pharos explorer metadata in `hardhat.config.*`.

## Typical Commands

Scan only:

```bash
python3 main.py scan --workspace /path/to/project --intent "deploy my staking contract"
```

Plan a deployment:

```bash
python3 main.py run \
  --workspace /path/to/project \
  --intent "deploy my main token" \
  --contract MainToken
```

Resume from cached state:

```bash
python3 main.py resume --workspace /path/to/project
```

Execute a deploy pipeline:

```bash
python3 main.py run \
  --workspace /path/to/project \
  --intent "deploy and verify my staking contract" \
  --contract StakingVault \
  --constructor-arg 0xabc... \
  --constructor-arg 1000000000000000000 \
  --execute
```

Sync a deployed address into env files:

```bash
python3 main.py sync \
  --workspace /path/to/project \
  --address 0x1234567890abcdef1234567890abcdef12345678 \
  --env-key STAKING_VAULT_ADDRESS \
  --create-missing-env
```

## Notes

- This skill is standalone. It uses Pharos conventions as reference, but does not depend on the
  `pharos-skill-engine-0.1.0` folder at runtime.
- Hardhat execution supports both viem-based and ethers-based projects. The skill prefers official Hardhat viem helpers when available.
- Planning mode is read-only. It does not write deployment scripts into the target workspace.
- Resume is scoped by workspace path. Use the same `--workspace` value when continuing a cached run.
- If toolchain commands are missing, the engine still produces an actionable plan and cache state.
