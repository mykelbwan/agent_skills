import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_NETWORKS = {
    "atlantic-testnet": {
        "rpcUrl": "https://atlantic.dplabs-internal.com",
        "explorerUrl": "https://atlantic.pharosscan.xyz/",
        "nativeToken": "PHRS",
    },
    "mainnet": {
        "rpcUrl": "https://rpc.pharos.xyz",
        "explorerUrl": "https://www.pharosscan.xyz/",
        "nativeToken": "PROS",
    },
}

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

DEFAULT_SELECTOR_LABELS = {
    "0x095ea7b3": "approve(address,uint256)",
    "0x23b872dd": "transferFrom(address,address,uint256)",
    "0x40c10f19": "mint(address,uint256)",
    "0x42966c68": "burn(uint256)",
    "0xa0712d68": "mint(uint256)",
    "0xa694fc3a": "stake(uint256)",
    "0x2e1a7d4d": "withdraw(uint256)",
    "0x3ccfd60b": "withdraw()",
    "0x379607f5": "claim()",
    "0x6a627842": "mint()",
    "0xa9059cbb": "transfer(address,uint256)",
    "0xb6b55f25": "deposit(uint256)",
    "0xd0e30db0": "deposit()",
    "0xd09de08a": "increment()",
    "0xe2bbb158": "deposit(uint256,address)",
}

DEFAULT_EVENT_LABELS = {
    "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925": "Approval(address,address,uint256)",
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef": "Transfer(address,address,uint256)",
}


class JsonRpcClient:
    def __init__(self, rpc_url: str) -> None:
        self.rpc_url = rpc_url
        self.next_id = 1

    def call(self, method: str, params: List[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": self.next_id,
            "method": method,
            "params": params,
        }
        self.next_id += 1
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.rpc_url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"RPC HTTP error {exc.code}: {message}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"RPC connection error: {exc}") from exc

        if "error" in result:
            raise RuntimeError(f"RPC error for {method}: {result['error']}")
        return result.get("result")


def normalize_address(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None:
        return None
    address = value.lower()
    if not address.startswith("0x") or len(address) != 42:
        raise ValueError(f"{field_name} must be a 0x-prefixed 20-byte address")
    int(address[2:], 16)
    return address


def parse_block(value: Any, latest_block: int) -> int:
    if value == "latest":
        return latest_block
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.startswith("0x"):
        return int(value, 16)
    return int(value)


def block_hex(block_number: int) -> str:
    return hex(block_number)


def load_config(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def merge_config(args: argparse.Namespace) -> Dict[str, Any]:
    config = load_config(args.config)
    network_name = args.network or config.get("network") or "atlantic-testnet"
    network = DEFAULT_NETWORKS.get(network_name)
    if not network:
        raise ValueError("network must be atlantic-testnet or mainnet")

    merged = {
        "network": network_name,
        "rpcUrl": args.rpc_url or config.get("rpcUrl") or network["rpcUrl"],
        "explorerUrl": config.get("explorerUrl") or network["explorerUrl"],
        "contractAddress": args.contract or config.get("contractAddress"),
        "walletAddress": args.wallet or config.get("walletAddress"),
        "fromBlock": args.from_block if args.from_block is not None else config.get("fromBlock", 1),
        "toBlock": args.to_block if args.to_block is not None else config.get("toBlock", "latest"),
        "mode": args.mode or config.get("mode", "combined"),
        "blockChunkSize": int(args.block_chunk_size or config.get("blockChunkSize", 500)),
        "selectorLabels": {**DEFAULT_SELECTOR_LABELS, **config.get("selectorLabels", {})},
        "eventLabels": {**DEFAULT_EVENT_LABELS, **config.get("eventLabels", {})},
        "fixture": config.get("fixture"),
    }
    if args.selector_label:
        for item in args.selector_label:
            selector, label = item.split("=", 1)
            merged["selectorLabels"][selector.lower()] = label
    if args.event_label:
        for item in args.event_label:
            topic, label = item.split("=", 1)
            merged["eventLabels"][topic.lower()] = label
    return merged


def selector_from_input(input_data: str) -> str:
    if not input_data or input_data == "0x" or len(input_data) < 10:
        return "0x"
    return input_data[:10].lower()


def rpc_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.startswith("0x"):
        return int(value, 16)
    return int(value)


def topic_contains_address(topic: str, address: str) -> bool:
    return topic.lower().endswith(address[2:].lower())


def log_matches_wallet(log: Dict[str, Any], wallet: Optional[str]) -> bool:
    if not wallet:
        return True
    for topic in log.get("topics", []):
        if topic_contains_address(topic, wallet):
            return True
    return False


def tx_matches(tx: Dict[str, Any], contract: str, wallet: Optional[str]) -> bool:
    to_address = normalize_address(tx.get("to"), "transaction.to") if tx.get("to") else None
    from_address = normalize_address(tx.get("from"), "transaction.from") if tx.get("from") else None
    if to_address != contract:
        return False
    if wallet and from_address != wallet:
        return False
    return True


def scan_transactions(
    client: JsonRpcClient,
    contract: str,
    wallet: Optional[str],
    from_block: int,
    to_block: int,
    selector_labels: Dict[str, str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for block_number in range(from_block, to_block + 1):
        block = client.call("eth_getBlockByNumber", [block_hex(block_number), True])
        if not block:
            continue
        timestamp = int(block.get("timestamp", "0x0"), 16)
        for tx in block.get("transactions", []):
            if not tx_matches(tx, contract, wallet):
                continue
            selector = selector_from_input(tx.get("input", "0x"))
            rows.append(
                {
                    "type": "transaction",
                    "blockNumber": int(tx["blockNumber"], 16) if tx.get("blockNumber") else block_number,
                    "timestamp": timestamp,
                    "transactionHash": tx.get("hash"),
                    "from": normalize_address(tx.get("from"), "transaction.from"),
                    "to": normalize_address(tx.get("to"), "transaction.to") if tx.get("to") else None,
                    "selector": selector,
                    "label": selector_labels.get(selector, "unknown_function"),
                    "valueWei": str(int(tx.get("value", "0x0"), 16)),
                    "input": tx.get("input", "0x"),
                }
            )
    return rows


def scan_fixture_transactions(
    fixture: Dict[str, Any],
    contract: str,
    wallet: Optional[str],
    from_block: int,
    to_block: int,
    selector_labels: Dict[str, str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for tx in fixture.get("transactions", []):
        block_number = rpc_int(tx.get("blockNumber"))
        if block_number < from_block or block_number > to_block:
            continue
        if not tx_matches(tx, contract, wallet):
            continue
        selector = selector_from_input(tx.get("input", "0x"))
        rows.append(
            {
                "type": "transaction",
                "blockNumber": block_number,
                "timestamp": rpc_int(tx.get("timestamp")),
                "transactionHash": tx.get("hash"),
                "from": normalize_address(tx.get("from"), "transaction.from"),
                "to": normalize_address(tx.get("to"), "transaction.to") if tx.get("to") else None,
                "selector": selector,
                "label": selector_labels.get(selector, "unknown_function"),
                "valueWei": str(rpc_int(tx.get("value", "0x0"))),
                "input": tx.get("input", "0x"),
            }
        )
    return rows


def scan_logs(
    client: JsonRpcClient,
    contract: str,
    wallet: Optional[str],
    from_block: int,
    to_block: int,
    block_chunk_size: int,
    event_labels: Dict[str, str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    current = from_block
    while current <= to_block:
        chunk_end = min(current + block_chunk_size - 1, to_block)
        logs = client.call(
            "eth_getLogs",
            [
                {
                    "address": contract,
                    "fromBlock": block_hex(current),
                    "toBlock": block_hex(chunk_end),
                }
            ],
        )
        for log in logs:
            if not log_matches_wallet(log, wallet):
                continue
            topic0 = log.get("topics", ["0x"])[0].lower()
            rows.append(
                {
                    "type": "event",
                    "blockNumber": int(log["blockNumber"], 16),
                    "transactionHash": log.get("transactionHash"),
                    "logIndex": int(log.get("logIndex", "0x0"), 16),
                    "address": normalize_address(log.get("address"), "log.address"),
                    "topic0": topic0,
                    "label": event_labels.get(topic0, "unknown_event"),
                    "topics": log.get("topics", []),
                    "data": log.get("data", "0x"),
                }
            )
        current = chunk_end + 1
    return rows


def scan_fixture_logs(
    fixture: Dict[str, Any],
    contract: str,
    wallet: Optional[str],
    from_block: int,
    to_block: int,
    event_labels: Dict[str, str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for log in fixture.get("logs", []):
        block_number = rpc_int(log.get("blockNumber"))
        if block_number < from_block or block_number > to_block:
            continue
        if normalize_address(log.get("address"), "log.address") != contract:
            continue
        if not log_matches_wallet(log, wallet):
            continue
        topic0 = log.get("topics", ["0x"])[0].lower()
        rows.append(
            {
                "type": "event",
                "blockNumber": block_number,
                "transactionHash": log.get("transactionHash"),
                "logIndex": rpc_int(log.get("logIndex", "0x0")),
                "address": normalize_address(log.get("address"), "log.address"),
                "topic0": topic0,
                "label": event_labels.get(topic0, "unknown_event"),
                "topics": log.get("topics", []),
                "data": log.get("data", "0x"),
            }
        )
    return rows


def make_timeline(
    transactions: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    explorer_url: str,
) -> List[Dict[str, Any]]:
    timeline: List[Dict[str, Any]] = []
    for tx in transactions:
        timeline.append(
            {
                "sortKey": [tx["blockNumber"], 0, tx["transactionHash"] or ""],
                "kind": "transaction",
                "blockNumber": tx["blockNumber"],
                "transactionHash": tx["transactionHash"],
                "label": tx["label"],
                "summary": f"{tx['from']} called {tx['label']} on {tx['to']}",
                "explorerUrl": f"{explorer_url.rstrip('/')}/tx/{tx['transactionHash']}",
                "raw": tx,
            }
        )
    for event in events:
        timeline.append(
            {
                "sortKey": [event["blockNumber"], 1, event["logIndex"]],
                "kind": "event",
                "blockNumber": event["blockNumber"],
                "transactionHash": event["transactionHash"],
                "label": event["label"],
                "summary": f"{event['address']} emitted {event['label']}",
                "explorerUrl": f"{explorer_url.rstrip('/')}/tx/{event['transactionHash']}",
                "raw": event,
            }
        )
    return sorted(timeline, key=lambda item: item["sortKey"])


def write_csv(path: Path, rows: List[Dict[str, Any]], fields: List[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def write_outputs(output_dir: Path, config: Dict[str, Any], transactions: List[Dict[str, Any]], events: List[Dict[str, Any]], timeline: List[Dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "network": config["network"],
        "contractAddress": config["contractAddress"],
        "walletAddress": config.get("walletAddress"),
        "fromBlock": config["fromBlock"],
        "toBlock": config["toBlock"],
        "mode": config["mode"],
        "transactionCount": len(transactions),
        "eventCount": len(events),
        "timelineCount": len(timeline),
    }

    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_dir / "timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")

    write_csv(
        output_dir / "transactions.csv",
        transactions,
        ["blockNumber", "transactionHash", "from", "to", "selector", "label", "valueWei", "input"],
    )
    write_csv(
        output_dir / "events.csv",
        events,
        ["blockNumber", "transactionHash", "logIndex", "address", "topic0", "label", "data"],
    )

    lines = [
        "# Protocol Interaction Timeline",
        "",
        f"Network: `{config['network']}`",
        f"Contract: `{config['contractAddress']}`",
        f"Wallet: `{config.get('walletAddress') or 'all wallets'}`",
        f"Blocks: `{config['fromBlock']}` to `{config['toBlock']}`",
        "",
    ]
    for item in timeline:
        lines.append(f"- Block `{item['blockNumber']}`: {item['summary']} ([tx]({item['explorerUrl']}))")
    if not timeline:
        lines.append("- No matching interactions found in the requested range.")
    (output_dir / "timeline.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def do_record(args: argparse.Namespace) -> int:
    config = merge_config(args)
    contract = normalize_address(config.get("contractAddress"), "contractAddress")
    if not contract or contract == ZERO_ADDRESS:
        raise ValueError("contractAddress must be set to a deployed contract address")
    wallet = normalize_address(config.get("walletAddress"), "walletAddress") if config.get("walletAddress") else None
    mode = config["mode"]
    if mode not in {"transactions", "logs", "combined"}:
        raise ValueError("mode must be transactions, logs, or combined")

    config["contractAddress"] = contract
    config["walletAddress"] = wallet

    fixture = config.get("fixture")
    client = None if fixture else JsonRpcClient(config["rpcUrl"])
    latest_block = int(fixture.get("latestBlock", 0)) if fixture else int(client.call("eth_blockNumber", []), 16)
    from_block = parse_block(config["fromBlock"], latest_block)
    to_block = parse_block(config["toBlock"], latest_block)
    if to_block < from_block:
        raise ValueError("toBlock must be greater than or equal to fromBlock")
    config["fromBlock"] = from_block
    config["toBlock"] = to_block

    transactions: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    if mode in {"transactions", "combined"}:
        if fixture:
            transactions = scan_fixture_transactions(fixture, contract, wallet, from_block, to_block, config["selectorLabels"])
        else:
            transactions = scan_transactions(client, contract, wallet, from_block, to_block, config["selectorLabels"])
    if mode in {"logs", "combined"}:
        if fixture:
            events = scan_fixture_logs(fixture, contract, wallet, from_block, to_block, config["eventLabels"])
        else:
            events = scan_logs(client, contract, wallet, from_block, to_block, config["blockChunkSize"], config["eventLabels"])

    timeline = make_timeline(transactions, events, config["explorerUrl"])
    write_outputs(Path(args.output_dir), config, transactions, events, timeline)
    print(
        json.dumps(
            {
                "outputDir": args.output_dir,
                "transactions": len(transactions),
                "events": len(events),
                "timelineItems": len(timeline),
            },
            indent=2,
        )
    )
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Pharos Protocol Interaction Recorder")
    subparsers = root.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record", help="Record protocol interactions")
    record.add_argument("--config")
    record.add_argument("--network")
    record.add_argument("--rpc-url")
    record.add_argument("--contract")
    record.add_argument("--wallet")
    record.add_argument("--from-block")
    record.add_argument("--to-block")
    record.add_argument("--mode", choices=["transactions", "logs", "combined"])
    record.add_argument("--block-chunk-size")
    record.add_argument("--selector-label", action="append", help="Format: 0x12345678=methodName(types)")
    record.add_argument("--event-label", action="append", help="Format: 0xtopic=EventName(types)")
    record.add_argument("--output-dir", required=True)
    record.set_defaults(func=do_record)

    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.func(args)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
