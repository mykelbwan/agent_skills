import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_NETWORK = {
    "name": "atlantic-testnet",
    "rpcUrl": "https://atlantic.dplabs-internal.com",
    "chainId": 688689,
    "explorerUrl": "https://atlantic.pharosscan.xyz/",
    "explorerApiUrl": "https://api.socialscan.io/pharos-atlantic-testnet",
    "nativeToken": "PHRS",
}

SKIP_DIRS = {
    ".git",
    "node_modules",
    "lib",
    "cache",
    "broadcast",
    "artifacts",
    "typechain-types",
    "__pycache__",
}

STEP_ORDER = [
    "scanned",
    "compiled",
    "gas_estimated",
    "deployed",
    "verified",
    "synced",
    "smoke_tested",
]


@dataclass
class ProjectInfo:
    workspace: Path
    framework: str
    config_path: Optional[Path]
    source_roots: List[Path]
    artifact_roots: List[Path]


def skill_root() -> Path:
    return Path(__file__).resolve().parent


def cache_path() -> Path:
    return skill_root() / "config" / "devops-cache.json"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def normalize_workspace_key(path: Path) -> str:
    return str(path.resolve())


def default_cache() -> Dict[str, Any]:
    return {
        "version": 2,
        "network": DEFAULT_NETWORK,
        "lastWorkspace": None,
        "runs": {},
    }


def load_cache() -> Dict[str, Any]:
    path = cache_path()
    if not path.exists():
        return default_cache()
    data = load_json(path)
    if "runs" not in data:
        upgraded = default_cache()
        last_run = data.get("lastRun")
        if isinstance(last_run, dict) and last_run.get("workspace"):
            key = normalize_workspace_key(Path(last_run["workspace"]))
            upgraded["runs"][key] = last_run
            upgraded["lastWorkspace"] = key
        return upgraded
    return data


def save_cache(cache: Dict[str, Any]) -> None:
    save_json(cache_path(), cache)


def load_workspace_dotenv(workspace: Path) -> None:
    env_path = workspace / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_private_key(execute: bool) -> Optional[str]:
    if not execute:
        return None
    value = os.environ.get("PRIVATE_KEY", "").strip()
    if not value:
        raise RuntimeError("PRIVATE_KEY is not set")
    return value


def private_key_blocked() -> Dict[str, Any]:
    return {
        "mode": "blocked",
        "ok": False,
        "reason": "private_key_not_set",
        "hint": "Set PRIVATE_KEY in the shell environment before executing write operations.",
    }


def has_private_key() -> bool:
    return bool(os.environ.get("PRIVATE_KEY", "").strip())


def find_project(workspace: Path) -> ProjectInfo:
    foundry = workspace / "foundry.toml"
    hardhat_configs = [
        workspace / "hardhat.config.ts",
        workspace / "hardhat.config.js",
        workspace / "hardhat.config.cjs",
        workspace / "hardhat.config.mjs",
    ]

    if foundry.exists():
        return ProjectInfo(
            workspace=workspace,
            framework="foundry",
            config_path=foundry,
            source_roots=[workspace / "src", workspace / "contracts"],
            artifact_roots=[workspace / "out"],
        )

    for config in hardhat_configs:
        if config.exists():
            return ProjectInfo(
                workspace=workspace,
                framework="hardhat",
                config_path=config,
                source_roots=[workspace / "contracts", workspace / "src"],
                artifact_roots=[workspace / "artifacts" / "contracts", workspace / "artifacts"],
            )

    return ProjectInfo(
        workspace=workspace,
        framework="unknown",
        config_path=None,
        source_roots=[workspace / "src", workspace / "contracts"],
        artifact_roots=[workspace / "out", workspace / "artifacts"],
    )


def discover_solidity_sources(project: ProjectInfo) -> List[Path]:
    search_roots = [root for root in project.source_roots if root.exists()]
    if not search_roots:
        search_roots = [project.workspace]

    results: List[Path] = []
    for search_root in search_roots:
        for root, dirs, files in os.walk(search_root):
            dirs[:] = [item for item in dirs if item not in SKIP_DIRS]
            for name in files:
                if name.endswith(".sol"):
                    results.append(Path(root) / name)
    return sorted(set(results))


def parse_contract_names(source_path: Path) -> List[str]:
    text = source_path.read_text(encoding="utf-8", errors="ignore")
    return re.findall(r"\bcontract\s+([A-Za-z_][A-Za-z0-9_]*)", text)


def discover_contracts(project: ProjectInfo) -> List[Dict[str, Any]]:
    contracts: List[Dict[str, Any]] = []
    for source in discover_solidity_sources(project):
        names = parse_contract_names(source)
        for contract_name in names:
            contracts.append(
                {
                    "contractName": contract_name,
                    "sourcePath": str(source),
                    "artifact": None,
                    "abi": None,
                    "bytecode": None,
                    "constructorInputs": [],
                }
            )
    return contracts


def artifact_candidates(project: ProjectInfo, contract_name: str) -> List[Path]:
    candidates: List[Path] = []
    for root in project.artifact_roots:
        if not root.exists():
            continue
        for path in root.rglob(f"{contract_name}.json"):
            candidates.append(path)
    return candidates


def enrich_with_artifact(project: ProjectInfo, contract: Dict[str, Any]) -> Dict[str, Any]:
    candidates = artifact_candidates(project, contract["contractName"])
    for path in candidates:
        try:
            data = load_json(path)
        except Exception:
            continue
        abi = data.get("abi")
        bytecode = data.get("bytecode") or data.get("deployedBytecode", {}).get("object")
        if isinstance(bytecode, dict):
            bytecode = bytecode.get("object")
        constructor_inputs = []
        if isinstance(abi, list):
            for item in abi:
                if item.get("type") == "constructor":
                    constructor_inputs = item.get("inputs", [])
                    break
        contract["artifact"] = str(path)
        contract["abi"] = abi
        contract["bytecode"] = bytecode
        contract["constructorInputs"] = constructor_inputs
        return contract
    return contract


def score_contract(contract: Dict[str, Any], intent: str, explicit_name: Optional[str]) -> int:
    name = contract["contractName"].lower()
    source_path = contract["sourcePath"].lower()
    score = 0
    if explicit_name and explicit_name.lower() == name:
        score += 100
    if name in intent:
        score += 50
    keywords = {
        "token": ["token", "erc20", "coin"],
        "staking": ["staking", "stake", "farm"],
        "vesting": ["vesting", "vest"],
        "vault": ["vault"],
    }
    for family, hints in keywords.items():
        if any(hint in intent for hint in hints) and any(marker in name or marker in source_path for marker in [family, *hints]):
            score += 20
    if any(bad in name or bad in source_path for bad in ("helper", "distributor", "script", "mock", "test", "airdrop")):
        score -= 25
    if contract.get("artifact"):
        score += 5
    return score


def select_contract(project: ProjectInfo, intent: str, explicit_name: Optional[str]) -> Dict[str, Any]:
    contracts = [enrich_with_artifact(project, item) for item in discover_contracts(project)]
    if not contracts:
        raise RuntimeError("No Solidity contracts found in workspace")
    lowered_intent = intent.lower()
    ranked = sorted(
        contracts,
        key=lambda item: score_contract(item, lowered_intent, explicit_name),
        reverse=True,
    )
    return ranked[0]


def command_exists(name: str) -> bool:
    return shutil.which(name, path=tool_path()) is not None


def tool_path() -> str:
    candidates = [
        str(Path.home() / ".foundry" / "bin"),
        str(Path.home() / ".config" / ".foundry" / "bin"),
        str(Path.home() / ".local" / "share" / "pnpm"),
        str(Path.home() / ".cargo" / "bin"),
    ]
    candidates.extend(glob.glob(str(Path.home() / ".config" / "nvm" / "versions" / "node" / "*" / "bin")))
    candidates.extend(glob.glob(str(Path.home() / ".nvm" / "versions" / "node" / "*" / "bin")))
    existing = [path for path in candidates if Path(path).exists()]
    return os.pathsep.join([*existing, os.environ.get("PATH", "")])


def tool_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = tool_path()
    if extra:
        env.update(extra)
    return env


def package_manager(workspace: Path) -> str:
    if (workspace / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (workspace / "yarn.lock").exists():
        return "yarn"
    return "npm"


def hardhat_command_prefix(workspace: Path) -> List[str]:
    pm = package_manager(workspace)
    if pm == "pnpm":
        return ["pnpm", "exec", "hardhat"]
    if pm == "yarn":
        return ["yarn", "hardhat"]
    return ["npx", "hardhat"]


def package_json(workspace: Path) -> Dict[str, Any]:
    path = workspace / "package.json"
    if not path.exists():
        return {}
    try:
        return load_json(path)
    except Exception:
        return {}


def has_hardhat_verify_support(workspace: Path) -> bool:
    manifest = package_json(workspace)
    deps: Dict[str, Any] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        values = manifest.get(key)
        if isinstance(values, dict):
            deps.update(values)
    if "@nomicfoundation/hardhat-verify" in deps or "@nomiclabs/hardhat-etherscan" in deps:
        return True

    config_paths = [
        workspace / "hardhat.config.ts",
        workspace / "hardhat.config.js",
        workspace / "hardhat.config.cjs",
        workspace / "hardhat.config.mjs",
    ]
    for config_path in config_paths:
        if config_path.exists():
            text = config_path.read_text(encoding="utf-8", errors="ignore")
            if "hardhat-verify" in text or "hardhat-etherscan" in text or "etherscan" in text:
                return True
    return False


def has_hardhat_ethers_support(workspace: Path) -> bool:
    manifest = package_json(workspace)
    deps: Dict[str, Any] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        values = manifest.get(key)
        if isinstance(values, dict):
            deps.update(values)
    if (
        "@nomicfoundation/hardhat-ethers" in deps
        or "@nomicfoundation/hardhat-toolbox-ethers" in deps
        or "@nomicfoundation/hardhat-toolbox" in deps
    ):
        return True

    config_paths = [
        workspace / "hardhat.config.ts",
        workspace / "hardhat.config.js",
        workspace / "hardhat.config.cjs",
        workspace / "hardhat.config.mjs",
    ]
    for config_path in config_paths:
        if config_path.exists():
            text = config_path.read_text(encoding="utf-8", errors="ignore")
            if "hardhat-ethers" in text or "toolbox-ethers" in text:
                return True
    return False


def has_hardhat_viem_support(workspace: Path) -> bool:
    manifest = package_json(workspace)
    deps: Dict[str, Any] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        values = manifest.get(key)
        if isinstance(values, dict):
            deps.update(values)
    if "@nomicfoundation/hardhat-viem" in deps or "@nomicfoundation/hardhat-toolbox-viem" in deps:
        return True

    config_paths = [
        workspace / "hardhat.config.ts",
        workspace / "hardhat.config.js",
        workspace / "hardhat.config.cjs",
        workspace / "hardhat.config.mjs",
    ]
    for config_path in config_paths:
        if config_path.exists():
            text = config_path.read_text(encoding="utf-8", errors="ignore")
            if "hardhat-viem" in text or "toolbox-viem" in text:
                return True
    return False


def run_command(command: List[str], cwd: Path, execute: bool) -> Dict[str, Any]:
    if not execute:
        return {"mode": "plan", "planned": True, "command": command, "cwd": str(cwd)}
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
        env=tool_env(),
    )
    return {
        "mode": "execute",
        "command": command,
        "cwd": str(cwd),
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def run_command_with_env(command: List[str], cwd: Path, execute: bool, env_overrides: Dict[str, str]) -> Dict[str, Any]:
    if not execute:
        return {
            "mode": "plan",
            "planned": True,
            "command": command,
            "cwd": str(cwd),
            "env": env_overrides,
        }
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
        env=tool_env(env_overrides),
    )
    return {
        "mode": "execute",
        "command": command,
        "cwd": str(cwd),
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def is_completed(result: Dict[str, Any]) -> bool:
    return bool(result.get("mode") == "execute" and result.get("ok"))


def compile_project(project: ProjectInfo, execute: bool) -> Dict[str, Any]:
    if project.framework == "foundry":
        if not command_exists("forge"):
            return {"mode": "blocked", "ok": False, "reason": "forge_not_installed", "command": ["forge", "build"]}
        return run_command(["forge", "build"], project.workspace, execute)
    if project.framework == "hardhat":
        pm = package_manager(project.workspace)
        if pm == "pnpm":
            command = ["pnpm", "exec", "hardhat", "compile"]
        elif command_exists("npx"):
            command = ["npx", "hardhat", "compile"]
        else:
            return {"mode": "blocked", "ok": False, "reason": "npx_not_installed", "command": ["npx", "hardhat", "compile"]}
        return run_command(command, project.workspace, execute)
    return {"mode": "blocked", "ok": False, "reason": "unsupported_framework"}


def constructor_signature(contract: Dict[str, Any]) -> str:
    types = [item.get("type", "bytes") for item in contract.get("constructorInputs", [])]
    return f"constructor({','.join(types)})"


def parse_arg_list(values: Optional[List[str]], raw: Optional[str]) -> List[str]:
    if values:
        return [item for item in values if item]
    if raw:
        return [raw]
    return []


def encode_constructor_args(contract: Dict[str, Any], constructor_args: List[str], workspace: Path, execute: bool) -> Dict[str, Any]:
    if not constructor_args:
        return {"mode": "execute" if execute else "plan", "ok": True, "encoded": None}
    if not command_exists("cast"):
        return {"mode": "blocked", "ok": False, "reason": "cast_not_installed"}

    command = ["cast", "abi-encode", constructor_signature(contract), *constructor_args]
    result = run_command(command, workspace, execute)
    if execute and result.get("ok"):
        result["encoded"] = result.get("stdout", "").strip()
    return result


def generate_deploy_script_content(project: ProjectInfo, contract: Dict[str, Any], constructor_args: List[str]) -> str:
    source_path = Path(contract["sourcePath"])
    relative_source = os.path.relpath(source_path, project.workspace).replace("\\", "/")
    constructor_comment = ", ".join(constructor_args) if constructor_args else "none"
    constructor_expr = ", ".join(constructor_args)
    deployment = f"new {contract['contractName']}({constructor_expr})" if constructor_expr else f"new {contract['contractName']}()"
    return f"""// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Script.sol";
import "forge-std/console.sol";
import "{relative_source}";

contract Deploy{contract['contractName']} is Script {{
    function run() external {{
        // Constructor args: {constructor_comment}
        vm.startBroadcast();

        {contract['contractName']} instance = {deployment};

        console.log("Contract address:", address(instance));
        vm.stopBroadcast();
    }}
}}
"""


def generate_hardhat_deploy_script_content() -> str:
    return """const hre = require("hardhat");

async function main() {
  const { ethers, artifacts } = hre;
  const contractName = process.env.PHAROS_CONTRACT_NAME;
  const rpcUrl = process.env.PHAROS_RPC_URL;
  const privateKey = process.env.PRIVATE_KEY;
  const constructorArgs = JSON.parse(process.env.PHAROS_CONSTRUCTOR_ARGS || "[]");
  const estimateOnly = process.env.PHAROS_ESTIMATE_ONLY === "1";

  if (!contractName || !rpcUrl || !privateKey) {
    throw new Error("Missing PHAROS_CONTRACT_NAME, PHAROS_RPC_URL, or PRIVATE_KEY");
  }

  const artifact = await artifacts.readArtifact(contractName);
  const provider = new ethers.JsonRpcProvider(rpcUrl);
  const wallet = new ethers.Wallet(privateKey, provider);
  const factory = new ethers.ContractFactory(artifact.abi, artifact.bytecode, wallet);
  const deployTx = await factory.getDeployTransaction(...constructorArgs);
  const estimatedGas = await provider.estimateGas({ ...deployTx, from: wallet.address });
  console.log("Estimated gas:", estimatedGas.toString());

  if (estimateOnly) {
    return;
  }

  const contract = await factory.deploy(...constructorArgs);
  await contract.waitForDeployment();
  console.log("Contract address:", await contract.getAddress());
  const deploymentTx = contract.deploymentTransaction();
  if (deploymentTx) {
    console.log("Deployment tx:", deploymentTx.hash);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""


def generate_hardhat_viem_deploy_script_content() -> str:
    return """import hre from "hardhat";

const { viem } = await hre.network.connect();
const contractName = process.env.PHAROS_CONTRACT_NAME;
const constructorArgs = JSON.parse(process.env.PHAROS_CONSTRUCTOR_ARGS || "[]");

if (!contractName) {
  throw new Error("Missing PHAROS_CONTRACT_NAME");
}

const contract = await viem.deployContract(contractName, constructorArgs);
console.log("Contract address:", contract.address);
"""


def generate_hardhat_viem_smoke_script_content() -> str:
    return """import hre from "hardhat";

const { viem } = await hre.network.connect();
const contractName = process.env.PHAROS_CONTRACT_NAME;
const deployedAddress = process.env.PHAROS_DEPLOYED_ADDRESS;
const method = process.env.PHAROS_SMOKE_METHOD;
const args = JSON.parse(process.env.PHAROS_SMOKE_ARGS || "[]");

if (!contractName || !deployedAddress || !method) {
  throw new Error("Missing smoke-test environment variables");
}

const publicClient = await viem.getPublicClient();
const contract = await viem.getContractAt(contractName, deployedAddress);
const hash = await contract.write[method](args);
console.log("Smoke tx:", hash);
const receipt = await publicClient.waitForTransactionReceipt({ hash });
console.log("Smoke status:", receipt.status);
"""


def generate_hardhat_smoke_script_content() -> str:
    return """const hre = require("hardhat");

async function main() {
  const { ethers, artifacts } = hre;
  const contractName = process.env.PHAROS_CONTRACT_NAME;
  const deployedAddress = process.env.PHAROS_DEPLOYED_ADDRESS;
  const rpcUrl = process.env.PHAROS_RPC_URL;
  const privateKey = process.env.PRIVATE_KEY;
  const method = process.env.PHAROS_SMOKE_METHOD;
  const args = JSON.parse(process.env.PHAROS_SMOKE_ARGS || "[]");

  if (!contractName || !deployedAddress || !rpcUrl || !privateKey || !method) {
    throw new Error("Missing smoke-test environment variables");
  }

  const artifact = await artifacts.readArtifact(contractName);
  const provider = new ethers.JsonRpcProvider(rpcUrl);
  const wallet = new ethers.Wallet(privateKey, provider);
  const contract = new ethers.Contract(deployedAddress, artifact.abi, wallet);
  const tx = await contract[method](...args);
  console.log("Smoke tx:", tx.hash);
  const receipt = await tx.wait();
  console.log("Smoke status:", receipt.status);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""


def write_workspace_script(project: ProjectInfo, relative_path: str, content: str, execute: bool) -> Dict[str, Any]:
    target = project.workspace / relative_path
    if execute:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return {"path": str(target), "content": content, "written": execute}


def generate_deploy_script(project: ProjectInfo, contract: Dict[str, Any], constructor_args: List[str], execute: bool) -> Dict[str, Any]:
    script_name = f"Deploy{contract['contractName']}.s.sol"
    script_path = project.workspace / "script" / script_name
    content = generate_deploy_script_content(project, contract, constructor_args)
    if execute:
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(content, encoding="utf-8")
    return {"path": str(script_path), "content": content, "written": execute}


def estimate_gas_plan(project: ProjectInfo, contract: Dict[str, Any], constructor_args: List[str], execute: bool) -> Dict[str, Any]:
    if project.framework == "hardhat":
        if has_hardhat_viem_support(project.workspace) and command_exists("cast") and contract.get("bytecode"):
            bytecode = contract["bytecode"]
            if isinstance(bytecode, dict):
                bytecode = bytecode.get("object")
            if not isinstance(bytecode, str) or not bytecode.startswith("0x"):
                return {"mode": "blocked", "ok": False, "reason": "invalid_bytecode"}
            if constructor_args:
                encoded = encode_constructor_args(contract, constructor_args, project.workspace, execute)
                if execute and not encoded.get("ok"):
                    return encoded
                if execute:
                    encoded_data = encoded.get("encoded")
                    if not encoded_data:
                        return {"mode": "blocked", "ok": False, "reason": "constructor_args_encoding_failed"}
                    command = ["cast", "estimate", "--rpc-url", DEFAULT_NETWORK["rpcUrl"], "--create", f"{bytecode}{encoded_data[2:]}"]
                    return run_command(command, project.workspace, True)
                command = ["cast", "estimate", "--rpc-url", DEFAULT_NETWORK["rpcUrl"], "--create", "<bytecode+encoded_constructor_args>"]
                return {"mode": "plan", "planned": True, "command": command, "cwd": str(project.workspace)}
            return run_command(["cast", "estimate", "--rpc-url", DEFAULT_NETWORK["rpcUrl"], "--create", bytecode], project.workspace, execute)
        elif has_hardhat_viem_support(project.workspace):
            return {
                "mode": "blocked",
                "ok": False,
                "reason": "cast_required_for_hardhat_viem_gas_estimate",
                "hint": "Install Foundry cast, or use deploy execution without a preflight gas estimate.",
            }
        elif not has_hardhat_ethers_support(project.workspace):
            return {
                "mode": "blocked",
                "ok": False,
                "reason": "hardhat_ethers_support_required",
                "hint": "Install and configure @nomicfoundation/hardhat-ethers or an ethers-based Hardhat toolbox.",
            }
        prefix = hardhat_command_prefix(project.workspace)
        if prefix[0] == "npx" and not command_exists("npx"):
            return {"mode": "blocked", "ok": False, "reason": "npx_not_installed"}
        if prefix[0] == "pnpm" and not command_exists("pnpm"):
            return {"mode": "blocked", "ok": False, "reason": "pnpm_not_installed"}
        if prefix[0] == "yarn" and not command_exists("yarn"):
            return {"mode": "blocked", "ok": False, "reason": "yarn_not_installed"}

        script_info = write_workspace_script(
            project,
            "scripts/pharos-estimate.js",
            generate_hardhat_deploy_script_content(),
            execute,
        )
        env_overrides = {
            "PHAROS_CONTRACT_NAME": contract["contractName"],
            "PHAROS_RPC_URL": DEFAULT_NETWORK["rpcUrl"],
            "PHAROS_CONSTRUCTOR_ARGS": json.dumps(constructor_args),
            "PHAROS_ESTIMATE_ONLY": "1",
        }
        if execute and not has_private_key():
            return private_key_blocked()
        if execute:
            env_overrides["PRIVATE_KEY"] = get_private_key(True) or ""
        result = run_command_with_env(
            [*prefix, "run", "--no-compile", "scripts/pharos-estimate.js"],
            project.workspace,
            execute,
            env_overrides,
        )
        result["scriptPath"] = script_info["path"]
        result["scriptWritten"] = script_info["written"]
        if not execute:
            result["scriptPreview"] = script_info["content"]
        return result

    if project.framework != "foundry":
        return {"mode": "blocked", "ok": False, "reason": "gas_estimation_requires_supported_framework"}
    if not command_exists("cast"):
        return {"mode": "blocked", "ok": False, "reason": "cast_not_installed"}
    if not contract.get("bytecode"):
        return {"mode": "blocked", "ok": False, "reason": "bytecode_missing"}

    bytecode = contract["bytecode"]
    if isinstance(bytecode, dict):
        bytecode = bytecode.get("object")
    if not isinstance(bytecode, str) or not bytecode.startswith("0x"):
        return {"mode": "blocked", "ok": False, "reason": "invalid_bytecode"}

    if constructor_args:
        encoded = encode_constructor_args(contract, constructor_args, project.workspace, execute)
        if execute and not encoded.get("ok"):
            return encoded
        if execute:
            encoded_data = encoded.get("encoded")
            if not encoded_data:
                return {"mode": "blocked", "ok": False, "reason": "constructor_args_encoding_failed"}
            command = ["cast", "estimate", "--rpc-url", DEFAULT_NETWORK["rpcUrl"], "--create", f"{bytecode}{encoded_data[2:]}"]
            return run_command(command, project.workspace, True)
        command = ["cast", "estimate", "--rpc-url", DEFAULT_NETWORK["rpcUrl"], "--create", "<bytecode+encoded_constructor_args>"]
        return {"mode": "plan", "planned": True, "command": command, "cwd": str(project.workspace)}

    return run_command(["cast", "estimate", "--rpc-url", DEFAULT_NETWORK["rpcUrl"], "--create", bytecode], project.workspace, execute)


def deploy_plan(project: ProjectInfo, contract: Dict[str, Any], constructor_args: List[str], execute: bool) -> Dict[str, Any]:
    if project.framework == "hardhat":
        if has_hardhat_viem_support(project.workspace):
            prefix = hardhat_command_prefix(project.workspace)
            if prefix[0] == "npx" and not command_exists("npx"):
                return {"mode": "blocked", "ok": False, "reason": "npx_not_installed"}
            if prefix[0] == "pnpm" and not command_exists("pnpm"):
                return {"mode": "blocked", "ok": False, "reason": "pnpm_not_installed"}
            if prefix[0] == "yarn" and not command_exists("yarn"):
                return {"mode": "blocked", "ok": False, "reason": "yarn_not_installed"}

            script_info = write_workspace_script(
                project,
                "scripts/pharos-deploy.ts",
                generate_hardhat_viem_deploy_script_content(),
                execute,
            )
            env_overrides = {
                "PHAROS_CONTRACT_NAME": contract["contractName"],
                "PHAROS_CONSTRUCTOR_ARGS": json.dumps(constructor_args),
            }
            result = run_command_with_env(
                [*prefix, "run", "--network", DEFAULT_NETWORK["name"], "--no-compile", "scripts/pharos-deploy.ts"],
                project.workspace,
                execute,
                env_overrides,
            )
            result["scriptPath"] = script_info["path"]
            result["scriptWritten"] = script_info["written"]
            result["runtime"] = "hardhat-viem"
            if not execute:
                result["scriptPreview"] = script_info["content"]
            return result

        if not has_hardhat_ethers_support(project.workspace):
            return {
                "mode": "blocked",
                "ok": False,
                "reason": "hardhat_ethers_support_required",
                "hint": "Install and configure @nomicfoundation/hardhat-ethers or an ethers-based Hardhat toolbox.",
            }
        prefix = hardhat_command_prefix(project.workspace)
        if prefix[0] == "npx" and not command_exists("npx"):
            return {"mode": "blocked", "ok": False, "reason": "npx_not_installed"}
        if prefix[0] == "pnpm" and not command_exists("pnpm"):
            return {"mode": "blocked", "ok": False, "reason": "pnpm_not_installed"}
        if prefix[0] == "yarn" and not command_exists("yarn"):
            return {"mode": "blocked", "ok": False, "reason": "yarn_not_installed"}

        script_info = write_workspace_script(
            project,
            "scripts/pharos-deploy.js",
            generate_hardhat_deploy_script_content(),
            execute,
        )
        env_overrides = {
            "PHAROS_CONTRACT_NAME": contract["contractName"],
            "PHAROS_RPC_URL": DEFAULT_NETWORK["rpcUrl"],
            "PHAROS_CONSTRUCTOR_ARGS": json.dumps(constructor_args),
            "PHAROS_ESTIMATE_ONLY": "0",
        }
        if execute and not has_private_key():
            return private_key_blocked()
        if execute:
            env_overrides["PRIVATE_KEY"] = get_private_key(True) or ""
        result = run_command_with_env(
            [*prefix, "run", "--no-compile", "scripts/pharos-deploy.js"],
            project.workspace,
            execute,
            env_overrides,
        )
        result["scriptPath"] = script_info["path"]
        result["scriptWritten"] = script_info["written"]
        if not execute:
            result["scriptPreview"] = script_info["content"]
        return result

    if project.framework != "foundry":
        return {"mode": "blocked", "ok": False, "reason": "deployment_requires_supported_framework"}
    if not command_exists("forge"):
        return {"mode": "blocked", "ok": False, "reason": "forge_not_installed"}
    if execute and not has_private_key():
        return private_key_blocked()

    source_path = Path(contract["sourcePath"])
    source_spec = f"{source_path}:{contract['contractName']}"
    command = [
        "forge",
        "create",
        source_spec,
        "--rpc-url",
        DEFAULT_NETWORK["rpcUrl"],
        "--private-key",
        get_private_key(execute) or "<PRIVATE_KEY>",
        "--broadcast",
    ]
    if constructor_args:
        command.extend(["--constructor-args", *constructor_args])
    result = run_command(command, project.workspace, execute)
    result["deployer"] = "forge-create"
    return result


def verify_plan(contract: Dict[str, Any], constructor_args: List[str], deployed_address: Optional[str], execute: bool, workspace: Path) -> Dict[str, Any]:
    if not deployed_address:
        return {"mode": "blocked", "ok": False, "reason": "missing_deployed_address"}
    project = find_project(workspace)
    if project.framework == "hardhat" and has_hardhat_verify_support(workspace):
        prefix = hardhat_command_prefix(workspace)
        if prefix[0] == "npx" and not command_exists("npx"):
            return {"mode": "blocked", "ok": False, "reason": "npx_not_installed"}
        if prefix[0] == "pnpm" and not command_exists("pnpm"):
            return {"mode": "blocked", "ok": False, "reason": "pnpm_not_installed"}
        if prefix[0] == "yarn" and not command_exists("yarn"):
            return {"mode": "blocked", "ok": False, "reason": "yarn_not_installed"}
        result = run_command(
            [*prefix, "verify", "--network", DEFAULT_NETWORK["name"], deployed_address, *constructor_args],
            workspace,
            execute,
        )
        result["verifier"] = "hardhat"
        result["note"] = "Hardhat verification on Pharos requires hardhat-verify plus a matching Pharos network and chain descriptor in hardhat.config."
        return result
    if project.framework == "hardhat":
        return {
            "mode": "blocked",
            "ok": False,
            "reason": "hardhat_verify_support_required",
            "hint": "Install and configure @nomicfoundation/hardhat-verify with Pharos explorer metadata, or run without --verify.",
        }
    if not command_exists("forge"):
        return {"mode": "blocked", "ok": False, "reason": "forge_not_installed"}

    source_path = Path(contract["sourcePath"])
    source_spec = f"{source_path}:{contract['contractName']}"
    command = [
        "forge",
        "verify-contract",
        deployed_address,
        source_spec,
        "--chain-id",
        str(DEFAULT_NETWORK["chainId"]),
        "--verifier-url",
        DEFAULT_NETWORK["explorerApiUrl"],
        "--verifier",
        "blockscout",
    ]
    if constructor_args:
        encoded = encode_constructor_args(contract, constructor_args, workspace, execute)
        if execute and not encoded.get("ok"):
            return encoded
        if execute:
            command.extend(["--constructor-args", encoded["encoded"]])
        else:
            command.extend(["--constructor-args", "<encoded_constructor_args>"])
    result = run_command(command, workspace, execute)
    result["verifier"] = "forge"
    return result


def update_env_file(path: Path, key: str, value: str, create_missing: bool) -> Optional[Dict[str, Any]]:
    if not path.exists() and not create_missing:
        return None

    existing_lines: List[str] = []
    if path.exists():
        existing_lines = path.read_text(encoding="utf-8").splitlines()

    replaced = False
    output: List[str] = []
    for line in existing_lines:
        if line.startswith(f"{key}="):
            output.append(f"{key}={value}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(f"{key}={value}")

    path.write_text("\n".join(output).strip() + "\n", encoding="utf-8")
    return {"file": str(path), "key": key, "value": value, "replaced": replaced}


def sync_address(workspace: Path, address: str, env_key: str, extra_paths: Optional[List[str]] = None, create_missing: bool = False) -> List[Dict[str, Any]]:
    targets = [workspace / ".env", workspace / ".env.local"]
    for extra in extra_paths or []:
        targets.append(workspace / extra)

    updated = []
    for target in targets:
        result = update_env_file(target, env_key, address, create_missing=create_missing)
        if result:
            updated.append(result)
    return updated


def smoke_test_plan(contract: Dict[str, Any], deployed_address: Optional[str], method: Optional[str], args: List[str], execute: bool, workspace: Path) -> Dict[str, Any]:
    if not deployed_address:
        return {"mode": "blocked", "ok": False, "reason": "missing_deployed_address"}
    if not method:
        return {"mode": "blocked", "ok": False, "reason": "missing_smoke_method"}
    project = find_project(workspace)
    if project.framework == "hardhat":
        if has_hardhat_viem_support(project.workspace):
            prefix = hardhat_command_prefix(workspace)
            if prefix[0] == "npx" and not command_exists("npx"):
                return {"mode": "blocked", "ok": False, "reason": "npx_not_installed"}
            if prefix[0] == "pnpm" and not command_exists("pnpm"):
                return {"mode": "blocked", "ok": False, "reason": "pnpm_not_installed"}
            if prefix[0] == "yarn" and not command_exists("yarn"):
                return {"mode": "blocked", "ok": False, "reason": "yarn_not_installed"}

            script_info = write_workspace_script(
                project,
                "scripts/pharos-smoke.ts",
                generate_hardhat_viem_smoke_script_content(),
                execute,
            )
            env_overrides = {
                "PHAROS_CONTRACT_NAME": contract["contractName"],
                "PHAROS_DEPLOYED_ADDRESS": deployed_address,
                "PHAROS_SMOKE_METHOD": method,
                "PHAROS_SMOKE_ARGS": json.dumps(args),
            }
            result = run_command_with_env(
                [*prefix, "run", "--network", DEFAULT_NETWORK["name"], "--no-compile", "scripts/pharos-smoke.ts"],
                workspace,
                execute,
                env_overrides,
            )
            result["scriptPath"] = script_info["path"]
            result["scriptWritten"] = script_info["written"]
            result["runtime"] = "hardhat-viem"
            if not execute:
                result["scriptPreview"] = script_info["content"]
            return result

        if not has_hardhat_ethers_support(project.workspace):
            return {
                "mode": "blocked",
                "ok": False,
                "reason": "hardhat_ethers_support_required",
                "hint": "Install and configure @nomicfoundation/hardhat-ethers or an ethers-based Hardhat toolbox.",
            }
        prefix = hardhat_command_prefix(workspace)
        if prefix[0] == "npx" and not command_exists("npx"):
            return {"mode": "blocked", "ok": False, "reason": "npx_not_installed"}
        if prefix[0] == "pnpm" and not command_exists("pnpm"):
            return {"mode": "blocked", "ok": False, "reason": "pnpm_not_installed"}
        if prefix[0] == "yarn" and not command_exists("yarn"):
            return {"mode": "blocked", "ok": False, "reason": "yarn_not_installed"}

        script_info = write_workspace_script(
            project,
            "scripts/pharos-smoke.js",
            generate_hardhat_smoke_script_content(),
            execute,
        )
        env_overrides = {
            "PHAROS_CONTRACT_NAME": contract["contractName"],
            "PHAROS_DEPLOYED_ADDRESS": deployed_address,
            "PHAROS_RPC_URL": DEFAULT_NETWORK["rpcUrl"],
            "PHAROS_SMOKE_METHOD": method,
            "PHAROS_SMOKE_ARGS": json.dumps(args),
        }
        if execute and not has_private_key():
            return private_key_blocked()
        if execute:
            env_overrides["PRIVATE_KEY"] = get_private_key(True) or ""
        result = run_command_with_env(
            [*prefix, "run", "--no-compile", "scripts/pharos-smoke.js"],
            workspace,
            execute,
            env_overrides,
        )
        result["scriptPath"] = script_info["path"]
        result["scriptWritten"] = script_info["written"]
        if not execute:
            result["scriptPreview"] = script_info["content"]
        return result
    if not command_exists("cast"):
        return {"mode": "blocked", "ok": False, "reason": "cast_not_installed"}
    if execute and not has_private_key():
        return private_key_blocked()

    cast_method = method if "(" in method else f"{method}()"
    command = [
        "cast",
        "send",
        deployed_address,
        cast_method,
        *args,
        "--private-key",
        get_private_key(execute) or "<PRIVATE_KEY>",
        "--rpc-url",
        DEFAULT_NETWORK["rpcUrl"],
    ]
    return run_command(command, workspace, execute)


def build_summary(run_state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "workspace": run_state.get("workspace"),
        "framework": run_state.get("framework"),
        "contract": run_state.get("contract", {}).get("contractName"),
        "steps": run_state.get("steps", {}),
        "deployedAddress": run_state.get("deployedAddress"),
        "envUpdates": run_state.get("envUpdates", []),
        "resumeFrom": next_incomplete_step(run_state.get("steps", {})),
    }


def cache_run(cache: Dict[str, Any], run_state: Dict[str, Any]) -> None:
    workspace_key = normalize_workspace_key(Path(run_state["workspace"]))
    cache["runs"][workspace_key] = run_state
    cache["lastWorkspace"] = workspace_key
    save_cache(cache)


def next_incomplete_step(steps: Dict[str, Any]) -> Optional[str]:
    for step in STEP_ORDER:
        if not steps.get(step):
            return step
    return None


def create_run_state(workspace: Path, project: ProjectInfo, intent: str, options: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "workspace": str(workspace),
        "framework": project.framework,
        "intent": intent,
        "network": DEFAULT_NETWORK,
        "steps": {step: False for step in STEP_ORDER},
        "deployedAddress": options.get("address"),
        "envUpdates": [],
        "options": options,
    }


def parse_deployed_address(command_result: Dict[str, Any]) -> Optional[str]:
    for field in ("stdout", "stderr"):
        text = command_result.get(field, "")
        for pattern in (
            r"Contract address:\s*(0x[a-fA-F0-9]{40})",
            r"contract address:\s*(0x[a-fA-F0-9]{40})",
            r"Deployed to:\s*(0x[a-fA-F0-9]{40})",
            r"deployed to:\s*(0x[a-fA-F0-9]{40})",
        ):
            match = re.search(pattern, text)
            if match:
                return match.group(1)
    return None


def refresh_contract(project: ProjectInfo, run_state: Dict[str, Any]) -> None:
    current = run_state["contract"]
    refreshed = enrich_with_artifact(project, current.copy())
    run_state["contract"] = refreshed


def apply_pipeline(project: ProjectInfo, run_state: Dict[str, Any], execute: bool) -> Dict[str, Any]:
    options = run_state["options"]
    constructor_args = options.get("constructorArgs", [])

    run_state["steps"]["scanned"] = True

    if not run_state["steps"]["compiled"]:
        compile_result = compile_project(project, execute)
        run_state["compile"] = compile_result
        run_state["steps"]["compiled"] = is_completed(compile_result)
        if is_completed(compile_result):
            refresh_contract(project, run_state)

    if not run_state["steps"]["gas_estimated"]:
        gas_result = estimate_gas_plan(project, run_state["contract"], constructor_args, execute)
        run_state["gasEstimate"] = gas_result
        run_state["steps"]["gas_estimated"] = is_completed(gas_result)

    if not run_state["steps"]["deployed"]:
        deploy_result = deploy_plan(project, run_state["contract"], constructor_args, execute)
        run_state["deploy"] = deploy_result
        run_state["steps"]["deployed"] = is_completed(deploy_result)
        if is_completed(deploy_result):
            run_state["deployedAddress"] = parse_deployed_address(deploy_result) or run_state.get("deployedAddress")

    should_verify = bool(options.get("verifyRequested"))
    if should_verify and not run_state["steps"]["verified"]:
        verify_result = verify_plan(
            run_state["contract"],
            constructor_args,
            run_state.get("deployedAddress"),
            execute,
            project.workspace,
        )
        run_state["verify"] = verify_result
        run_state["steps"]["verified"] = is_completed(verify_result)

    sync_env_key = options.get("syncEnvKey")
    if sync_env_key and not run_state["steps"]["synced"]:
        if execute and run_state.get("deployedAddress"):
            updates = sync_address(
                project.workspace,
                run_state["deployedAddress"],
                sync_env_key,
                options.get("syncPaths"),
                create_missing=bool(options.get("createMissingEnv")),
            )
            run_state["envUpdates"] = updates
            run_state["steps"]["synced"] = bool(updates)
        else:
            run_state["syncPlan"] = {
                "envKey": sync_env_key,
                "paths": [".env", ".env.local", *(options.get("syncPaths") or [])],
                "createMissing": bool(options.get("createMissingEnv")),
            }

    smoke_method = options.get("smokeMethod")
    if smoke_method and not run_state["steps"]["smoke_tested"]:
        smoke_result = smoke_test_plan(
            run_state["contract"],
            run_state.get("deployedAddress"),
            smoke_method,
            options.get("smokeArgs", []),
            execute,
            project.workspace,
        )
        run_state["smokeTest"] = smoke_result
        run_state["steps"]["smoke_tested"] = is_completed(smoke_result)

    return run_state


def do_scan(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    load_workspace_dotenv(workspace)
    project = find_project(workspace)
    contract = select_contract(project, args.intent or "", args.contract)
    output = {
        "workspace": str(workspace),
        "framework": project.framework,
        "configPath": str(project.config_path) if project.config_path else None,
        "selectedContract": contract,
    }
    print(json.dumps(output, indent=2))
    return 0


def build_options(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "contractName": args.contract,
        "constructorArgs": parse_arg_list(getattr(args, "constructor_arg", None), getattr(args, "constructor_args", None)),
        "verifyRequested": bool(getattr(args, "verify", False) or "verify" in (getattr(args, "intent", "") or "").lower()),
        "syncEnvKey": getattr(args, "sync_env_key", None),
        "syncPaths": getattr(args, "sync_path", None) or [],
        "createMissingEnv": bool(getattr(args, "create_missing_env", False)),
        "smokeMethod": getattr(args, "smoke_method", None),
        "smokeArgs": parse_arg_list(getattr(args, "smoke_arg", None), getattr(args, "smoke_args", None)),
        "address": getattr(args, "address", None),
    }


def do_run(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    load_workspace_dotenv(workspace)
    project = find_project(workspace)
    options = build_options(args)
    run_state = create_run_state(workspace, project, args.intent or "", options)
    run_state["contract"] = select_contract(project, args.intent or "", args.contract)
    run_state = apply_pipeline(project, run_state, execute=args.execute)

    cache = load_cache()
    cache_run(cache, run_state)
    print(json.dumps(build_summary(run_state), indent=2))
    return 0


def do_resume(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    load_workspace_dotenv(workspace)
    cache = load_cache()
    workspace_key = normalize_workspace_key(workspace)
    run_state = cache.get("runs", {}).get(workspace_key)
    if not run_state:
        raise RuntimeError(f"No cached run found for workspace: {workspace}")

    project = find_project(workspace)
    run_state = apply_pipeline(project, run_state, execute=args.execute)
    cache_run(cache, run_state)
    print(json.dumps(build_summary(run_state), indent=2))
    return 0


def do_sync(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    load_workspace_dotenv(workspace)
    updates = sync_address(
        workspace,
        args.address,
        args.env_key,
        args.sync_path,
        create_missing=bool(args.create_missing_env),
    )
    cache = load_cache()
    project = find_project(workspace)
    workspace_key = normalize_workspace_key(workspace)
    run_state = cache.get("runs", {}).get(workspace_key) or create_run_state(workspace, project, "sync only", {})
    run_state["deployedAddress"] = args.address
    run_state["envUpdates"] = updates
    run_state["steps"]["synced"] = bool(updates)
    cache_run(cache, run_state)
    print(json.dumps({"updated": updates}, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Pharos AI DevOps Engineer")
    subparsers = root.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Scan workspace and infer target contract")
    scan.add_argument("--workspace", required=True)
    scan.add_argument("--intent", default="")
    scan.add_argument("--contract")
    scan.set_defaults(func=do_scan)

    run = subparsers.add_parser("run", help="Run or plan the deploy pipeline")
    run.add_argument("--workspace", required=True)
    run.add_argument("--intent", default="")
    run.add_argument("--contract")
    run.add_argument("--constructor-args")
    run.add_argument("--constructor-arg", action="append")
    run.add_argument("--verify", action="store_true")
    run.add_argument("--execute", action="store_true")
    run.add_argument("--address")
    run.add_argument("--sync-env-key")
    run.add_argument("--sync-path", action="append")
    run.add_argument("--create-missing-env", action="store_true")
    run.add_argument("--smoke-method")
    run.add_argument("--smoke-args")
    run.add_argument("--smoke-arg", action="append")
    run.set_defaults(func=do_run)

    resume = subparsers.add_parser("resume", help="Resume the cached pipeline for a workspace")
    resume.add_argument("--workspace", required=True)
    resume.add_argument("--execute", action="store_true")
    resume.set_defaults(func=do_resume)

    sync = subparsers.add_parser("sync", help="Sync an address into local env files")
    sync.add_argument("--workspace", required=True)
    sync.add_argument("--address", required=True)
    sync.add_argument("--env-key", required=True)
    sync.add_argument("--sync-path", action="append")
    sync.add_argument("--create-missing-env", action="store_true")
    sync.set_defaults(func=do_sync)

    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
