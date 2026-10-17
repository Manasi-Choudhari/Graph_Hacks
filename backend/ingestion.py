"""
FraudScope AI — Dynamic Data Ingestion Engine
Parses CSV and JSON data (accounts, transactions, infrastructure) and
efficiently loads/merges it into the FalkorDB graph database.
"""

import io
import csv
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from db import get_graph
import tools as graph_tools


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def _to_bool(val: Any, default: bool = False) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("true", "1", "yes", "y", "t"):
            return True
        if v in ("false", "0", "no", "n", "f"):
            return False
    return default


def get_template(template_type: str = "csv") -> dict:
    """Return template data and headers for CSV or JSON."""
    if template_type.lower() == "json":
        return {
            "format": "json",
            "content": json.dumps(
                {
                    "accounts": [
                        {
                            "id": "ACC_EXAMPLE_01",
                            "name": "Acme Holdings LLC",
                            "country": "US",
                            "balance": 250000.0,
                            "risk_score": 0.85,
                            "entity_type": "shell_company",
                            "is_suspicious": True,
                        },
                        {
                            "id": "ACC_EXAMPLE_02",
                            "name": "Jane Doe",
                            "country": "GB",
                            "balance": 14200.0,
                            "risk_score": 0.65,
                            "entity_type": "mule",
                            "is_suspicious": True,
                        },
                    ],
                    "transactions": [
                        {
                            "source_id": "ACC_EXAMPLE_01",
                            "target_id": "ACC_EXAMPLE_02",
                            "amount": 9500.0,
                            "currency": "USD",
                            "channel": "wire",
                            "pattern": "structuring",
                            "is_suspicious": True,
                            "timestamp": _now_iso(),
                        }
                    ],
                    "infrastructure": [
                        {
                            "account_id": "ACC_EXAMPLE_01",
                            "ip_address": "198.51.100.24",
                            "device_fingerprint": "a1b2c3d4e5f60718",
                        },
                        {
                            "account_id": "ACC_EXAMPLE_02",
                            "ip_address": "198.51.100.24",
                            "device_fingerprint": "a1b2c3d4e5f60718",
                        },
                    ],
                },
                indent=2,
            ),
            "filename": "fraudscope_template.json",
            "content_type": "application/json",
        }

    # Default: CSV template
    csv_rows = [
        [
            "source_id",
            "source_name",
            "target_id",
            "target_name",
            "amount",
            "currency",
            "timestamp",
            "channel",
            "pattern",
            "source_ip",
            "source_device",
            "is_suspicious",
        ],
        [
            "SHELL_ALPHA",
            "Apex Global Trading",
            "MULE_BETA",
            "Robert Chen",
            "9600.00",
            "USD",
            _now_iso(),
            "wire",
            "structuring",
            "192.168.10.45",
            "dev_fingerprint_881",
            "true",
        ],
        [
            "MULE_BETA",
            "Robert Chen",
            "CASHOUT_GAMMA",
            "BitGate Global OTC",
            "45000.00",
            "USDT",
            _now_iso(),
            "crypto",
            "layering",
            "192.168.10.45",
            "dev_fingerprint_881",
            "true",
        ],
    ]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(csv_rows)
    return {
        "format": "csv",
        "content": output.getvalue(),
        "filename": "fraudscope_transactions_template.csv",
        "content_type": "text/csv",
    }


def get_sample_syndicate_dataset() -> dict:
    """Pre-built sample dataset representing an international offshore layering ring."""
    now = _now_iso()
    return {
        "accounts": [
            {
                "id": "SHELL_PACIFIC_VAULT",
                "name": "Pacific Vault Capital Partners",
                "country": "KY",
                "balance": 1850000.0,
                "risk_score": 0.94,
                "entity_type": "shell_company",
                "is_suspicious": True,
            },
            {
                "id": "MULE_KIM_SOO",
                "name": "Kim Soo-jin",
                "country": "KR",
                "balance": 38400.0,
                "risk_score": 0.82,
                "entity_type": "mule",
                "is_suspicious": True,
            },
            {
                "id": "MULE_ALEX_RIVERA",
                "name": "Alex Rivera",
                "country": "PA",
                "balance": 41200.0,
                "risk_score": 0.79,
                "entity_type": "mule",
                "is_suspicious": True,
            },
            {
                "id": "MULE_TARIQ_MANSOUR",
                "name": "Tariq Mansour",
                "country": "AE",
                "balance": 29800.0,
                "risk_score": 0.81,
                "entity_type": "mule",
                "is_suspicious": True,
            },
            {
                "id": "CASHOUT_NEXUS_CRYPTO",
                "name": "Nexus OTC Liquidity Desk",
                "country": "SC",
                "balance": 3400000.0,
                "risk_score": 0.45,
                "entity_type": "crypto_exchange",
                "is_suspicious": False,
            },
        ],
        "transactions": [
            {
                "source_id": "SHELL_PACIFIC_VAULT",
                "target_id": "MULE_KIM_SOO",
                "amount": 9800.0,
                "currency": "USD",
                "channel": "wire",
                "pattern": "structuring",
                "is_suspicious": True,
                "timestamp": now,
            },
            {
                "source_id": "SHELL_PACIFIC_VAULT",
                "target_id": "MULE_ALEX_RIVERA",
                "amount": 9750.0,
                "currency": "wire",
                "channel": "wire",
                "pattern": "structuring",
                "is_suspicious": True,
                "timestamp": now,
            },
            {
                "source_id": "SHELL_PACIFIC_VAULT",
                "target_id": "MULE_TARIQ_MANSOUR",
                "amount": 9900.0,
                "currency": "USD",
                "channel": "wire",
                "pattern": "structuring",
                "is_suspicious": True,
                "timestamp": now,
            },
            {
                "source_id": "MULE_KIM_SOO",
                "target_id": "CASHOUT_NEXUS_CRYPTO",
                "amount": 65000.0,
                "currency": "USDT",
                "channel": "crypto",
                "pattern": "layering",
                "is_suspicious": True,
                "timestamp": now,
            },
            {
                "source_id": "MULE_ALEX_RIVERA",
                "target_id": "CASHOUT_NEXUS_CRYPTO",
                "amount": 58000.0,
                "currency": "USDT",
                "channel": "crypto",
                "pattern": "layering",
                "is_suspicious": True,
                "timestamp": now,
            },
            {
                "source_id": "MULE_TARIQ_MANSOUR",
                "target_id": "CASHOUT_NEXUS_CRYPTO",
                "amount": 72000.0,
                "currency": "USDT",
                "channel": "crypto",
                "pattern": "layering",
                "is_suspicious": True,
                "timestamp": now,
            },
        ],
        "infrastructure": [
            {
                "account_id": "SHELL_PACIFIC_VAULT",
                "ip_address": "45.134.22.89",
                "device_fingerprint": "fp_syndicate_vpn_01",
            },
            {
                "account_id": "MULE_KIM_SOO",
                "ip_address": "45.134.22.89",
                "device_fingerprint": "fp_syndicate_vpn_01",
            },
            {
                "account_id": "MULE_ALEX_RIVERA",
                "ip_address": "45.134.22.89",
                "device_fingerprint": "fp_syndicate_vpn_01",
            },
        ],
    }


def parse_csv_content(text: str) -> dict[str, list[dict]]:
    """
    Parse CSV text into accounts, transactions, and infrastructure records.
    Supports either unified transaction logs or account logs.
    """
    reader = csv.DictReader(io.StringIO(text.strip()))
    accounts: dict[str, dict] = {}
    transactions: list[dict] = []
    infrastructure: list[dict] = []

    for row in reader:
        # Normalize keys (strip whitespace, lowercase)
        norm_row = {k.strip().lower(): v.strip() for k, v in row.items() if k}

        # Case 1: Transaction log format (source_id and target_id present)
        if "source_id" in norm_row or "target_id" in norm_row:
            src_id = norm_row.get("source_id") or f"ACC_{_uid()}"
            dst_id = norm_row.get("target_id") or f"ACC_{_uid()}"
            amount = _to_float(norm_row.get("amount", 0))
            is_susp = _to_bool(
                norm_row.get("is_suspicious"),
                default=(9000 <= amount < 10000 or norm_row.get("pattern") in ("structuring", "layering")),
            )

            # Ensure source account
            if src_id not in accounts:
                accounts[src_id] = {
                    "id": src_id,
                    "name": norm_row.get("source_name") or src_id,
                    "country": norm_row.get("source_country") or "US",
                    "balance": _to_float(norm_row.get("source_balance"), 50000.0),
                    "risk_score": 0.8 if is_susp else 0.15,
                    "entity_type": "shell_company" if src_id.startswith("SHELL_") else ("mule" if src_id.startswith("MULE_") else "individual"),
                    "is_suspicious": is_susp,
                }

            # Ensure target account
            if dst_id not in accounts:
                accounts[dst_id] = {
                    "id": dst_id,
                    "name": norm_row.get("target_name") or dst_id,
                    "country": norm_row.get("target_country") or "US",
                    "balance": _to_float(norm_row.get("target_balance"), 25000.0),
                    "risk_score": 0.8 if is_susp else 0.15,
                    "entity_type": "crypto_exchange" if dst_id.startswith("CASHOUT_") else "individual",
                    "is_suspicious": is_susp if not dst_id.startswith("CASHOUT_") else False,
                }

            tx = {
                "source_id": src_id,
                "target_id": dst_id,
                "amount": amount,
                "currency": norm_row.get("currency") or "USD",
                "channel": norm_row.get("channel") or "wire",
                "pattern": norm_row.get("pattern") or ("structuring" if 9000 <= amount < 10000 else "transfer"),
                "timestamp": norm_row.get("timestamp") or _now_iso(),
                "is_suspicious": is_susp,
            }
            transactions.append(tx)

            # Check infrastructure fields
            src_ip = norm_row.get("source_ip") or norm_row.get("ip_address") or norm_row.get("ip")
            src_dev = norm_row.get("source_device") or norm_row.get("device")
            if src_ip or src_dev:
                infrastructure.append({"account_id": src_id, "ip_address": src_ip, "device_fingerprint": src_dev})

            dst_ip = norm_row.get("target_ip")
            dst_dev = norm_row.get("target_device")
            if dst_ip or dst_dev:
                infrastructure.append({"account_id": dst_id, "ip_address": dst_ip, "device_fingerprint": dst_dev})

        # Case 2: Accounts-only CSV
        elif "id" in norm_row or "account_id" in norm_row:
            acc_id = norm_row.get("id") or norm_row.get("account_id") or f"ACC_{_uid()}"
            accounts[acc_id] = {
                "id": acc_id,
                "name": norm_row.get("name") or acc_id,
                "country": norm_row.get("country") or "US",
                "balance": _to_float(norm_row.get("balance"), 10000.0),
                "risk_score": _to_float(norm_row.get("risk_score"), 0.1),
                "entity_type": norm_row.get("entity_type") or "individual",
                "is_suspicious": _to_bool(norm_row.get("is_suspicious"), False),
            }
            ip = norm_row.get("ip_address") or norm_row.get("ip")
            dev = norm_row.get("device_fingerprint") or norm_row.get("device")
            if ip or dev:
                infrastructure.append({"account_id": acc_id, "ip_address": ip, "device_fingerprint": dev})

    return {
        "accounts": list(accounts.values()),
        "transactions": transactions,
        "infrastructure": infrastructure,
    }


def parse_json_content(content: str | dict | list) -> dict[str, list[dict]]:
    """Parse JSON content into accounts, transactions, and infrastructure."""
    if isinstance(content, str):
        data = json.loads(content)
    else:
        data = content

    if isinstance(data, list):
        # List of transactions or accounts
        if data and ("source_id" in data[0] or "target_id" in data[0]):
            csv_like = []
            for item in data:
                csv_like.append({k.lower(): str(v) for k, v in item.items()})
            # Convert list of dicts through csv-like normalizer
            return parse_csv_content(csv_dict_list_to_csv_text(csv_like))
        else:
            return {"accounts": data, "transactions": [], "infrastructure": []}

    if isinstance(data, dict):
        return {
            "accounts": data.get("accounts", []),
            "transactions": data.get("transactions", []),
            "infrastructure": data.get("infrastructure", []),
        }

    return {"accounts": [], "transactions": [], "infrastructure": []}


def csv_dict_list_to_csv_text(rows: list[dict]) -> str:
    if not rows:
        return ""
    output = io.StringIO()
    headers = list(rows[0].keys())
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def ingest_into_falkordb(data: dict, mode: str = "append") -> dict:
    """
    Ingest validated dataset into FalkorDB.
    mode: 'append' (default) preserves existing graph, 'replace' wipes first.
    """
    g = get_graph()
    started = datetime.now()

    if mode.lower() == "replace":
        # Delete existing data
        g.query("MATCH (n) DETACH DELETE n")

    accounts = data.get("accounts", [])
    transactions = data.get("transactions", [])
    infra_list = data.get("infrastructure", [])

    acc_created = 0
    tx_created = 0
    ips_created = 0
    devs_created = 0
    alerts_created = 0
    total_volume = 0.0

    # 1. Ingest Accounts
    for acc in accounts:
        acc_id = acc.get("id") or f"ACC_{_uid()}"
        name = acc.get("name") or acc_id
        country = acc.get("country") or "US"
        balance = _to_float(acc.get("balance"), 10000.0)
        risk = _to_float(acc.get("risk_score"), 0.1)
        susp = _to_bool(acc.get("is_suspicious"), risk > 0.5)
        etype = acc.get("entity_type") or "individual"

        g.query(
            """
            MERGE (a:Account {id: $id})
            SET a.name = $name,
                a.country = $country,
                a.balance = $balance,
                a.risk_score = $risk,
                a.is_suspicious = $susp,
                a.entity_type = $etype,
                a.updated_at = $ts
            """,
            {
                "id": acc_id,
                "name": name,
                "country": country,
                "balance": balance,
                "risk": risk,
                "susp": susp,
                "etype": etype,
                "ts": _now_iso(),
            },
        )
        acc_created += 1

        # Create alert for high risk accounts if flagged
        if susp or risk > 0.75:
            al_id = f"ALERT_{_uid()}"
            severity = "CRITICAL" if risk > 0.8 else "HIGH"
            g.query(
                """
                MATCH (a:Account {id: $acc})
                MERGE (al:AlertEvent {id: $al_id})
                SET al.type = 'ANOMALOUS_INGESTION',
                    al.severity = $severity,
                    al.timestamp = $ts,
                    al.resolved = false
                MERGE (a)-[:HAS_ALERT]->(al)
                """,
                {
                    "acc": acc_id,
                    "al_id": al_id,
                    "severity": severity,
                    "ts": _now_iso(),
                },
            )
            alerts_created += 1

    # 2. Ingest Transactions
    for tx in transactions:
        src = tx.get("source_id")
        dst = tx.get("target_id")
        if not src or not dst:
            continue

        amount = _to_float(tx.get("amount"), 0.0)
        total_volume += amount
        currency = tx.get("currency") or "USD"
        channel = tx.get("channel") or "wire"
        pattern = tx.get("pattern") or ("structuring" if 9000 <= amount < 10000 else "transfer")
        is_susp = _to_bool(tx.get("is_suspicious"), pattern in ("structuring", "layering"))
        ts = tx.get("timestamp") or _now_iso()
        tx_id = tx.get("id") or f"TX_{_uid()}"

        # Ensure both endpoints exist
        g.query("MERGE (:Account {id: $id})", {"id": src})
        g.query("MERGE (:Account {id: $id})", {"id": dst})

        g.query(
            """
            MATCH (src:Account {id: $src}), (dst:Account {id: $dst})
            CREATE (src)-[t:TRANSACTED_WITH {id: $tx_id}]->(dst)
            SET t.amount = $amount,
                t.currency = $currency,
                t.channel = $channel,
                t.pattern = $pattern,
                t.is_suspicious = $is_susp,
                t.timestamp = $ts
            """,
            {
                "src": src,
                "dst": dst,
                "tx_id": tx_id,
                "amount": amount,
                "currency": currency,
                "channel": channel,
                "pattern": pattern,
                "is_susp": is_susp,
                "ts": ts,
            },
        )
        tx_created += 1

    # 3. Ingest Infrastructure (IPs and Devices)
    seen_ips = set()
    seen_devs = set()
    for inf in infra_list:
        acc_id = inf.get("account_id")
        if not acc_id:
            continue

        ip_addr = inf.get("ip_address")
        if ip_addr:
            ip_node_id = f"IP_{str(ip_addr).replace('.', '_')}"
            g.query(
                "MERGE (ip:IPAddress {address: $addr, id: $id})",
                {"addr": str(ip_addr), "id": ip_node_id},
            )
            g.query(
                """
                MATCH (a:Account {id: $acc}), (ip:IPAddress {id: $ip})
                MERGE (a)-[:USES_IP]->(ip)
                """,
                {"acc": acc_id, "ip": ip_node_id},
            )
            if ip_addr not in seen_ips:
                seen_ips.add(ip_addr)
                ips_created += 1

        dev_fp = inf.get("device_fingerprint")
        if dev_fp:
            dev_id = f"DEV_{dev_fp[:12]}"
            g.query(
                "MERGE (d:Device {fingerprint: $fp, id: $id})",
                {"fp": str(dev_fp), "id": dev_id},
            )
            g.query(
                """
                MATCH (a:Account {id: $acc}), (d:Device {id: $dev})
                MERGE (a)-[:USES_DEVICE]->(d)
                """,
                {"acc": acc_id, "dev": dev_id},
            )
            if dev_fp not in seen_devs:
                seen_devs.add(dev_fp)
                devs_created += 1

    # 4. Post-ingestion housekeeping: rebuild maxFlow projections and clear cache
    try:
        graph_tools.build_flow_projection()
    except Exception as e:
        print(f"[WARN] Rebuilding flow projection after ingestion failed: {e}")

    try:
        from agent import clear_tool_cache
        clear_tool_cache()
    except Exception:
        pass

    elapsed = (datetime.now() - started).total_seconds() * 1000

    overview = graph_tools.get_graph_overview()

    return {
        "status": "success",
        "mode": mode,
        "accounts_created_or_updated": acc_created,
        "transactions_created": tx_created,
        "ips_linked": ips_created,
        "devices_linked": devs_created,
        "alerts_generated": alerts_created,
        "total_volume_usd": round(total_volume, 2),
        "elapsed_ms": round(elapsed, 1),
        "overview": overview,
    }
