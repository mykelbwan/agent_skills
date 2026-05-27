"""
Pharos Intelligent Airdrop Filter
Scans Pharos contract event logs, filters wallets by interaction count and balance,
and exports airdrop-ready CSV files compatible with Pharos batch airdrop scripts.
"""
import argparse
import csv
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request

# keccak256("balanceOf(address)") selector
BALANCE_OF_SELECTOR = "70a08231"

# Default retry settings for transient RPC failures
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.5  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("airdrop-filter")


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def normalize_address(value):
    if not isinstance(value, str):
        raise ValueError("Address must be a string")
    address = value.lower()
    if not address.startswith("0x") or len(address) != 42:
        raise ValueError(f"Invalid address: {value}")
    int(address[2:], 16)  # validate hex
    return address


def address_from_topic(topic):
    if not isinstance(topic, str) or not topic.startswith("0x") or len(topic) != 66:
        return None
    return "0x" + topic[-40:].lower()


def pad_address(address):
    return address[2:].rjust(64, "0")


def encode_balance_of(address):
    return "0x" + BALANCE_OF_SELECTOR + pad_address(address)


def hex_to_int(value, field_name):
    if value in (None, "0x"):
        return 0
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ValueError(f"{field_name} returned a non-hex value: {value!r}")
    return int(value, 16)


def chunked(sequence, size):
    if size <= 0:
        raise ValueError("Chunk size must be greater than zero")
    for index in range(0, len(sequence), size):
        yield sequence[index:index + size]


def wei_to_ether(wei):
    """Convert wei integer to human-readable ether string for display."""
    return f"{wei / 10**18:.6f}"

class JsonRpcClient:
    def __init__(self, rpc_url, retries=DEFAULT_RETRIES, retry_delay=DEFAULT_RETRY_DELAY):
        self.rpc_url = rpc_url
        self.retries = retries
        self.retry_delay = retry_delay
        self._next_id = 1

    def _request(self, payload, attempt=0):
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.rpc_url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            # Retry on 429 (rate limit) and 5xx (server errors)
            if exc.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                wait = self.retry_delay * (2 ** attempt)
                log.warning("RPC HTTP %s — retrying in %.1fs (attempt %s/%s)", exc.code, wait, attempt + 1, self.retries)
                time.sleep(wait)
                return self._request(payload, attempt + 1)
            raise RuntimeError(f"RPC HTTP error {exc.code}: {message}") from exc
        except urllib.error.URLError as exc:
            if attempt < self.retries:
                wait = self.retry_delay * (2 ** attempt)
                log.warning("RPC connection error — retrying in %.1fs (attempt %s/%s): %s", wait, attempt + 1, self.retries, exc)
                time.sleep(wait)
                return self._request(payload, attempt + 1)
            raise RuntimeError(f"RPC connection error: {exc}") from exc

    def call(self, method, params):
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params,
        }
        self._next_id += 1
        response = self._request(payload)
        if "error" in response:
            raise RuntimeError(f"RPC error for {method}: {response['error']}")
        return response["result"]

    def batch_call(self, calls):
        payload = []
        ids = []
        for method, params in calls:
            rpc_id = self._next_id
            self._next_id += 1
            ids.append(rpc_id)
            payload.append({
                "jsonrpc": "2.0",
                "id": rpc_id,
                "method": method,
                "params": params,
            })

        responses = self._request(payload)
        if not isinstance(responses, list):
            raise RuntimeError("Expected batch JSON-RPC response list")

        indexed = {item["id"]: item for item in responses}
        ordered = []
        for rpc_id in ids:
            item = indexed.get(rpc_id)
            if item is None:
                raise RuntimeError(f"Missing batch response id {rpc_id}")
            if "error" in item:
                raise RuntimeError(f"RPC batch error: {item['error']}")
            ordered.append(item["result"])
        return ordered

def fetch_logs(client, config):
    from_block = config["fromBlock"]
    to_block = config["toBlock"]
    chunk_size = int(config.get("blockChunkSize", 2000))
    max_block_span = int(config.get("maxBlockSpan", 100000))
    if chunk_size <= 0:
        raise ValueError("blockChunkSize must be greater than zero")

    latest_block_hex = client.call("eth_blockNumber", [])
    latest_block = int(latest_block_hex, 16)

    if from_block == "latest":
        raise ValueError("fromBlock cannot be 'latest'; use an explicit block number")

    start = int(from_block, 16) if isinstance(from_block, str) and from_block.startswith("0x") else int(from_block)
    end = latest_block if to_block == "latest" else (
        int(to_block, 16) if isinstance(to_block, str) and to_block.startswith("0x") else int(to_block)
    )

    if end < start:
        raise ValueError("toBlock must be >= fromBlock")
    if end - start + 1 > max_block_span:
        raise ValueError(
            f"Requested block range is too large ({end - start + 1} blocks). "
            f"Set a smaller range or increase maxBlockSpan explicitly."
        )

    event_filter = config.get("eventFilter", {})
    if "topics" in event_filter:
        topics = event_filter["topics"]
    elif "topic0" in event_filter:
        topics = [event_filter["topic0"]]
    else:
        topics = []

    contract_address = normalize_address(config["contractAddress"])
    total_blocks = end - start + 1
    chunks_total = (total_blocks + chunk_size - 1) // chunk_size

    logs = []
    current = start
    chunk_num = 0
    while current <= end:
        chunk_end = min(current + chunk_size - 1, end)
        chunk_num += 1
        log.info("Fetching logs: blocks %s–%s  [chunk %s/%s]", current, chunk_end, chunk_num, chunks_total)

        params = {
            "address": contract_address,
            "fromBlock": hex(current),
            "toBlock": hex(chunk_end),
        }
        if topics:
            params["topics"] = topics

        batch = client.call("eth_getLogs", [params])
        logs.extend(batch)
        current = chunk_end + 1

    log.info("Fetched %s total logs across %s block chunks", len(logs), chunk_num)
    return logs, latest_block


def aggregate_addresses(logs, config):
    counts = {}
    excluded = {normalize_address(item) for item in config.get("excludeAddresses", [])}
    count_mode = config.get("interactionCountMode", "unique_logs")
    if count_mode not in ("unique_logs", "source_hits"):
        raise ValueError("interactionCountMode must be 'unique_logs' or 'source_hits'")

    for entry in logs:
        topics = entry.get("topics", [])
        addresses_in_log = set()

        for source in config.get("addressSources", []):
            source_type = source.get("type")
            address = None

            if source_type == "topic":
                index = int(source["index"])
                if index >= len(topics):
                    continue
                address = address_from_topic(topics[index])

            elif source_type == "data":
                # Extract a 20-byte address from eth_getLogs data field at a given byte offset.
                # offset is the byte position of the address (e.g. 12 for the first ABI-encoded address).
                data = entry.get("data", "0x")
                offset = int(source.get("offset", 12))
                raw = data[2:]  # strip 0x
                start_char = offset * 2
                if len(raw) < start_char + 40:
                    continue
                address = "0x" + raw[start_char:start_char + 40].lower()

            else:
                continue

            if not address or address in excluded:
                continue
            address = normalize_address(address)
            if address in excluded:
                continue

            if count_mode == "source_hits":
                counts[address] = counts.get(address, 0) + 1
            else:
                addresses_in_log.add(address)

        if count_mode == "unique_logs":
            for address in addresses_in_log:
                counts[address] = counts.get(address, 0) + 1

    log.info("Aggregated %s unique addresses from logs", len(counts))
    return counts

def fetch_native_balances(client, addresses, latest_block, request_chunk_size):
    result = {}
    total = len(addresses)
    fetched = 0
    for group in chunked(addresses, request_chunk_size):
        calls = [("eth_getBalance", [address, hex(latest_block)]) for address in group]
        balances = client.batch_call(calls)
        for address, balance in zip(group, balances):
            result[address] = hex_to_int(balance, f"native balance for {address}")
        fetched += len(group)
        log.info("Native balances: %s/%s", fetched, total)
    return result


def fetch_erc20_balances(client, addresses, token_address, latest_block, request_chunk_size):
    token = normalize_address(token_address)
    result = {}
    total = len(addresses)
    fetched = 0
    for group in chunked(addresses, request_chunk_size):
        calls = [
            ("eth_call", [{"to": token, "data": encode_balance_of(address)}, hex(latest_block)])
            for address in group
        ]
        balances = client.batch_call(calls)
        for address, balance in zip(group, balances):
            result[address] = hex_to_int(balance, f"ERC20 balance for {address}")
        fetched += len(group)
        log.info("ERC20 balances: %s/%s", fetched, total)
    return result


def has_fixture(config):
    return isinstance(config.get("fixture"), dict)


def load_fixture_logs(config):
    fixture = config["fixture"]
    logs = fixture.get("logs", [])
    if not isinstance(logs, list):
        raise ValueError("fixture.logs must be a list")
    latest_block = int(fixture.get("latestBlock", config.get("toBlock", 0)))
    log.info("Using fixture mode: %s logs at latest block %s", len(logs), latest_block)
    return logs, latest_block


def load_fixture_balances(config, addresses):
    fixture = config["fixture"]
    raw_balances = fixture.get("balances", {})
    if not isinstance(raw_balances, dict):
        raise ValueError("fixture.balances must be an object")

    balances = {}
    for address in addresses:
        value = raw_balances.get(address) or raw_balances.get(address.lower())
        balances[address] = int(value or 0)
    log.info("Fixture balances loaded for %s/%s addresses", len(balances), len(addresses))
    return balances


def qualify(address_counts, balances, config):
    minimum_interactions = int(config["qualification"]["minInteractions"])
    balance_check = config["qualification"]["balanceCheck"]
    minimum_balance = int(balance_check["minBalanceWei"])
    balance_type = balance_check["type"]
    airdrop_amount = str(config["airdrop"]["amountWei"])

    # Optional: per-address airdrop scaling by interaction count
    tiered = config["airdrop"].get("tiered", [])
    # tiered example: [{"minInteractions": 10, "amountWei": "200000000000000000"}, ...]
    # sorted descending so the first matching tier wins
    tiered_sorted = sorted(tiered, key=lambda t: int(t["minInteractions"]), reverse=True)

    qualified = []
    disqualified = []

    for address in sorted(address_counts):
        interaction_count = address_counts[address]
        balance = balances.get(address, 0)

        if interaction_count < minimum_interactions:
            disqualified.append({
                "address": address,
                "interactionCount": interaction_count,
                "balanceWei": str(balance),
                "balanceDisplay": wei_to_ether(balance),
                "reason": "interaction_count_below_threshold",
            })
            continue

        if balance < minimum_balance:
            disqualified.append({
                "address": address,
                "interactionCount": interaction_count,
                "balanceWei": str(balance),
                "balanceDisplay": wei_to_ether(balance),
                "reason": f"balance_below_threshold ({balance_type})",
            })
            continue

        # Determine airdrop amount — tiered overrides flat if configured
        amount = airdrop_amount
        for tier in tiered_sorted:
            if interaction_count >= int(tier["minInteractions"]):
                amount = str(tier["amountWei"])
                break

        qualified.append({
            "address": address,
            "interactionCount": interaction_count,
            "balanceWei": str(balance),
            "balanceDisplay": wei_to_ether(balance),
            "amountWei": amount,
        })

    log.info("Qualified: %s  |  Disqualified: %s", len(qualified), len(disqualified))
    return qualified, disqualified

def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_outputs(output_dir, summary, qualified, disqualified):
    ensure_dir(output_dir)

    summary_path = os.path.join(output_dir, "summary.json")
    qualified_csv_path = os.path.join(output_dir, "qualified.csv")
    qualified_txt_path = os.path.join(output_dir, "qualified.txt")
    disqualified_csv_path = os.path.join(output_dir, "disqualified.csv")

    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    write_csv(
        qualified_csv_path,
        [{"address": item["address"], "amount": item["amountWei"]} for item in qualified],
        ["address", "amount"],
    )
    write_csv(
        disqualified_csv_path,
        disqualified,
        ["address", "interactionCount", "balanceWei", "balanceDisplay", "reason"],
    )

    with open(qualified_txt_path, "w", encoding="utf-8") as handle:
        for item in qualified:
            handle.write(item["address"] + "\n")

    return {
        "summary": summary_path,
        "qualifiedCsv": qualified_csv_path,
        "qualifiedTxt": qualified_txt_path,
        "disqualifiedCsv": disqualified_csv_path,
    }


def build_summary(config, latest_block, log_count, unique_addresses, qualified, disqualified, files):
    balance_check = config["qualification"]["balanceCheck"]
    return {
        "network": {
            "rpcUrl": config["rpcUrl"],
            "latestBlock": latest_block,
        },
        "scan": {
            "contractAddress": normalize_address(config["contractAddress"]),
            "fromBlock": config["fromBlock"],
            "toBlock": config["toBlock"],
            "matchedLogs": log_count,
            "uniqueAddresses": unique_addresses,
            "interactionCountMode": config.get("interactionCountMode", "unique_logs"),
        },
        "qualification": {
            "minInteractions": config["qualification"]["minInteractions"],
            "balanceCheckType": balance_check["type"],
            "minBalanceWei": balance_check["minBalanceWei"],
            "qualifiedCount": len(qualified),
            "disqualifiedCount": len(disqualified),
        },
        "airdrop": {
            "amountWei": config["airdrop"]["amountWei"],
            "tieredRules": config["airdrop"].get("tiered", []),
        },
        "files": files,
    }

def main():
    parser = argparse.ArgumentParser(description="Build a Pharos airdrop allowlist from event logs.")
    parser.add_argument("--config", required=True, help="Path to the JSON config file")
    parser.add_argument("--output-dir", required=True, help="Directory for generated reports")
    parser.add_argument("--dry-run", action="store_true", help="Scan logs only; skip balance checks and output")
    parser.add_argument("--verbose", action="store_true", help="Show DEBUG-level logs")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = read_json(args.config)

    if has_fixture(config):
        logs, latest_block = load_fixture_logs(config)
        client = None
    else:
        client = JsonRpcClient(config["rpcUrl"])
        logs, latest_block = fetch_logs(client, config)

    address_counts = aggregate_addresses(logs, config)
    addresses = sorted(address_counts.keys())

    if args.dry_run:
        log.info("Dry run: %s unique addresses found across %s logs. Skipping balance check.", len(addresses), len(logs))
        print(json.dumps({"uniqueAddresses": len(addresses), "matchedLogs": len(logs)}, indent=2))
        return

    request_chunk_size = int(config.get("requestChunkSize", 100))
    if request_chunk_size <= 0:
        raise ValueError("requestChunkSize must be greater than zero")
    balance_check = config["qualification"]["balanceCheck"]
    balance_type = balance_check["type"]

    if has_fixture(config):
        balances = load_fixture_balances(config, addresses)
    elif balance_type == "native":
        balances = fetch_native_balances(client, addresses, latest_block, request_chunk_size)
    elif balance_type == "erc20":
        balances = fetch_erc20_balances(
            client, addresses, balance_check["tokenAddress"], latest_block, request_chunk_size,
        )
    else:
        raise ValueError(f"Unsupported balance check type: {balance_type}")

    qualified, disqualified = qualify(address_counts, balances, config)

    output_files = {
        "summary": os.path.join(args.output_dir, "summary.json"),
        "qualifiedCsv": os.path.join(args.output_dir, "qualified.csv"),
        "qualifiedTxt": os.path.join(args.output_dir, "qualified.txt"),
        "disqualifiedCsv": os.path.join(args.output_dir, "disqualified.csv"),
    }
    summary = build_summary(config, latest_block, len(logs), len(addresses), qualified, disqualified, output_files)
    write_outputs(args.output_dir, summary, qualified, disqualified)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.error("%s", exc)
        sys.exit(1)
