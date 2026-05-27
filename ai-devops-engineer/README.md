# AI DevOps Engineer

AI DevOps Engineer is a Pharos Agent Center skill that turns a local smart-contract deployment workflow into one conversational pipeline.

It scans a Foundry or Hardhat workspace, selects the target Solidity contract, compiles it, estimates deployment gas on Pharos Atlantic testnet, deploys, verifies, syncs the deployed address into local env/config files, and optionally runs a smoke-test transaction.

## Why This Is Useful

Smart-contract developers usually jump between their editor, terminal, block explorer, deployment scripts, and frontend config after every deploy. This skill keeps that workflow inside the agent loop:

- Detects Foundry and Hardhat projects automatically.
- Infers the contract from a prompt like `deploy my counter contract`.
- Uses local artifacts to recover ABI, bytecode, and constructor inputs.
- Records resumable state in `config/devops-cache.json`.
- Automatically derives a neutral env key such as `COUNTER_ADDRESS` when no sync key is provided.
- Avoids storing or printing private keys.
- Supports Foundry directly and Hardhat projects using official ethers or viem plugins.

## Target Network

Default network: Pharos Atlantic testnet

- RPC URL: `https://atlantic.dplabs-internal.com`
- Chain ID: `688689`
- Explorer: `https://atlantic.pharosscan.xyz/`
- Explorer API: `https://api.socialscan.io/pharos-atlantic-testnet`
- Native token: `PHRS`

## Requirements

- Python 3.9+
- Foundry for Foundry projects: `forge` and `cast`
- Node.js plus `npm`, `pnpm`, or `yarn` for Hardhat projects
- A funded Pharos Atlantic testnet wallet for real deployments
- `PRIVATE_KEY` set only in your shell environment when executing write operations

Do not commit `.env`, private keys, broadcast files, or local caches.

## Skill Layout

```text
ai-devops-engineer/
  SKILL.md
  README.md
  main.py
  config/
    devops-cache.json
  examples/
    foundry-counter/
      README.md
      foundry.toml
      src/Counter.sol
  references/
    demo-guide.md
    pipeline-guide.md
  SUBMISSION.md
```

## Quick Demo

From this repository root:

Compile the demo workspace:

```bash
forge build --root ai-devops-engineer/examples/foundry-counter
```

```bash
python3 ai-devops-engineer/main.py scan \
  --workspace ai-devops-engineer/examples/foundry-counter \
  --intent "deploy my counter contract" \
  --contract Counter
```

Plan the full pipeline without writing to chain:

```bash
python3 ai-devops-engineer/main.py run \
  --workspace ai-devops-engineer/examples/foundry-counter \
  --intent "deploy and verify my counter contract" \
  --contract Counter \
  --verify \
  --smoke-method increment
```

Execute on Pharos Atlantic testnet after funding your deployer wallet:

```bash
export PRIVATE_KEY=your_testnet_private_key

python3 ai-devops-engineer/main.py run \
  --workspace ai-devops-engineer/examples/foundry-counter \
  --intent "deploy, verify, sync, and smoke test my counter contract" \
  --contract Counter \
  --verify \
  --execute \
  --create-missing-env \
  --smoke-method increment
```

By default, the skill syncs the deployed address into an env key derived from the contract name. For `Counter`, that key is `COUNTER_ADDRESS`. Override it with `--sync-env-key`, or disable automatic env sync with `--no-auto-sync-env`.

If a step fails or verification needs a retry:

```bash
python3 ai-devops-engineer/main.py resume \
  --workspace ai-devops-engineer/examples/foundry-counter \
  --execute
```

## Hardhat Support

Hardhat projects are supported when they use official Hardhat plugins:

- viem path: `@nomicfoundation/hardhat-viem` or `@nomicfoundation/hardhat-toolbox-viem`
- ethers path: `@nomicfoundation/hardhat-ethers`, `@nomicfoundation/hardhat-toolbox-ethers`, or `@nomicfoundation/hardhat-toolbox`
- verification: `@nomicfoundation/hardhat-verify` with Pharos network and explorer metadata in `hardhat.config.*`

The skill intentionally does not treat bare `ethers` or `viem` dependencies as Hardhat runtime support.

## Safety Notes

- Planning mode is the default and does not write deployment scripts into the target workspace.
- Execution mode requires `--execute`.
- Write operations require `PRIVATE_KEY`.
- The private key is never saved to `config/devops-cache.json`.
- Deployment state is workspace-scoped, so multiple projects can be resumed independently.

## Demo Assets

Use `references/demo-guide.md` for the recording script and screenshots checklist.
Use `SUBMISSION.md` as the Discord submission template.
