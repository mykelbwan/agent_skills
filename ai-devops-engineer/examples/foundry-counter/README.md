# Foundry Counter Demo

This is a tiny Foundry workspace for recording the AI DevOps Engineer demo.

## One-Time Setup

Install Foundry if needed. No external Solidity dependency is required for this tiny demo contract.

## Compile

```bash
forge build
```

## Use With The Skill

From the repository root:

```bash
python3 ai-devops-engineer/main.py scan \
  --workspace ai-devops-engineer/examples/foundry-counter \
  --intent "deploy my counter contract" \
  --contract Counter
```

For a real Pharos Atlantic testnet deploy:

```bash
export PRIVATE_KEY=your_testnet_private_key

python3 ai-devops-engineer/main.py run \
  --workspace ai-devops-engineer/examples/foundry-counter \
  --intent "deploy, verify, sync, and smoke test my counter contract" \
  --contract Counter \
  --verify \
  --execute \
  --sync-env-key COUNTER_ADDRESS \
  --create-missing-env \
  --smoke-method increment
```

Do not show or commit the private key.
