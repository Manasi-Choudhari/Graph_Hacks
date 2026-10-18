"""
Synthetic fraud dataset seeder for FalkorDB.

Creates a realistic financial crime graph with:
- Accounts, Entities, Transactions
- Shell companies, Money mule networks
- Shared IPs / Devices (classic fraud signals)
- Known fraud rings seeded as ground truth
"""

import random
import sys
from datetime import datetime, timedelta
from faker import Faker
from db import get_graph

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

fake = Faker()
random.seed(42)


def _uid() -> str:
    return f"{random.getrandbits(32):08x}"


def seed_graph():
    g = get_graph()
    random.seed(42)
    Faker.seed(42)

    print("🌱 Seeding FraudScope graph into FalkorDB...")
    g.query("MATCH (n) DETACH DELETE n")

    # ── 1. Legitimate accounts ───────────────────────────────────────────────
    legit_accounts = []
    for _ in range(60):
        acc_id = f"ACC_{_uid()}"
        name = fake.name()
        country = fake.country_code()
        risk = round(random.uniform(0.01, 0.25), 3)
        g.query(
            """
            MERGE (a:Account {id: $id})
            SET a.name = $name,
                a.country = $country,
                a.balance = $balance,
                a.risk_score = $risk,
                a.is_suspicious = false,
                a.created_at = $ts
            """,
            {
                "id": acc_id,
                "name": name,
                "country": country,
                "balance": round(random.uniform(1000, 500000), 2),
                "risk": risk,
                "ts": datetime.utcnow().isoformat(),
            },
        )
        legit_accounts.append(acc_id)

    # ── 2. Fraud ring accounts (shell companies + mules) ────────────────────
    fraud_rings = []
    for ring_num in range(3):
        ring = []
        # Central shell company
        shell_id = f"SHELL_{_uid()}"
        g.query(
            """
            MERGE (a:Account {id: $id})
            SET a.name = $name,
                a.country = $country,
                a.balance = $balance,
                a.risk_score = $risk,
                a.is_suspicious = true,
                a.ring_id = $ring,
                a.entity_type = 'shell_company',
                a.created_at = $ts
            """,
            {
                "id": shell_id,
                "name": f"Phantom Holdings {ring_num + 1} Ltd",
                "country": random.choice(["CY", "VG", "KY", "PA", "SC"]),
                "balance": round(random.uniform(50000, 2000000), 2),
                "risk": round(random.uniform(0.75, 0.98), 3),
                "ring": f"ring_{ring_num}",
                "ts": datetime.utcnow().isoformat(),
            },
        )
        ring.append(shell_id)

        # Mule accounts
        for _ in range(5):
            mule_id = f"MULE_{_uid()}"
            g.query(
                """
                MERGE (a:Account {id: $id})
                SET a.name = $name,
                    a.country = $country,
                    a.balance = $balance,
                    a.risk_score = $risk,
                    a.is_suspicious = true,
                    a.ring_id = $ring,
                    a.entity_type = 'mule',
                    a.created_at = $ts
                """,
                {
                    "id": mule_id,
                    "name": fake.name(),
                    "country": fake.country_code(),
                    "balance": round(random.uniform(500, 50000), 2),
                    "risk": round(random.uniform(0.6, 0.9), 3),
                    "ring": f"ring_{ring_num}",
                    "ts": datetime.utcnow().isoformat(),
                },
            )
            ring.append(mule_id)
        fraud_rings.append(ring)

    # ── 3. Transactions ──────────────────────────────────────────────────────
    all_accounts = legit_accounts + [acc for ring in fraud_rings for acc in ring]

    # Legit transactions
    for _ in range(150):
        src, dst = random.sample(legit_accounts, 2)
        tx_id = f"TX_{_uid()}"
        amount = round(random.uniform(10, 5000), 2)
        ts = (datetime.utcnow() - timedelta(days=random.randint(0, 90))).isoformat()
        g.query(
            """
            MATCH (src:Account {id: $src}), (dst:Account {id: $dst})
            MERGE (src)-[t:TRANSACTED_WITH {id: $tx_id}]->(dst)
            SET t.amount = $amount,
                t.currency = $currency,
                t.timestamp = $ts,
                t.is_suspicious = false,
                t.channel = $channel
            """,
            {
                "src": src,
                "dst": dst,
                "tx_id": tx_id,
                "amount": amount,
                "currency": "USD",
                "ts": ts,
                "channel": random.choice(["wire", "ach", "card", "crypto"]),
            },
        )

    # Fraud ring transactions (circular layering)
    for ring in fraud_rings:
        shell = ring[0]
        mules = ring[1:]

        # Inject → distribute → collect (classic money laundering)
        for mule in mules:
            for _ in range(random.randint(3, 7)):
                tx_id = f"TX_{_uid()}"
                amount = round(random.uniform(9000, 9999), 2)  # structuring
                ts = (
                    datetime.utcnow() - timedelta(days=random.randint(0, 30))
                ).isoformat()
                g.query(
                    """
                    MATCH (src:Account {id: $src}), (dst:Account {id: $dst})
                    MERGE (src)-[t:TRANSACTED_WITH {id: $tx_id}]->(dst)
                    SET t.amount = $amount,
                        t.currency = $currency,
                        t.timestamp = $ts,
                        t.is_suspicious = true,
                        t.channel = 'wire',
                        t.pattern = 'structuring'
                    """,
                    {
                        "src": shell,
                        "dst": mule,
                        "tx_id": tx_id,
                        "amount": amount,
                        "currency": "USD",
                        "ts": ts,
                    },
                )

        # Mule → shell (collection)
        for mule in mules:
            tx_id = f"TX_{_uid()}"
            g.query(
                """
                MATCH (src:Account {id: $src}), (dst:Account {id: $dst})
                MERGE (src)-[t:TRANSACTED_WITH {id: $tx_id}]->(dst)
                SET t.amount = $amount,
                    t.currency = $currency,
                    t.timestamp = $ts,
                    t.is_suspicious = true,
                    t.channel = 'crypto',
                    t.pattern = 'layering'
                """,
                {
                    "src": mule,
                    "dst": shell,
                    "tx_id": tx_id,
                    "amount": round(random.uniform(40000, 80000), 2),
                    "currency": "USDT",
                    "ts": datetime.utcnow().isoformat(),
                },
            )

    # Layering chain: mule → mule → … → cash-out exchange account
    for ring_num, ring in enumerate(fraud_rings):
        cashout_id = f"CASHOUT_{_uid()}"
        g.query(
            """
            MERGE (a:Account {id: $id})
            SET a.name = $name, a.country = $country, a.balance = $balance,
                a.risk_score = $risk, a.is_suspicious = false,
                a.entity_type = 'crypto_exchange', a.created_at = $ts
            """,
            {
                "id": cashout_id,
                "name": f"{random.choice(['Nova', 'Orbit', 'Zenith'])}Swap Exchange {ring_num + 1}",
                "country": random.choice(["SC", "VG", "MT"]),
                "balance": round(random.uniform(1e6, 5e6), 2),
                "risk": round(random.uniform(0.3, 0.5), 3),
                "ts": datetime.utcnow().isoformat(),
            },
        )
        chain = ring[1:] + [cashout_id]
        for src, dst in zip(chain, chain[1:]):
            for _ in range(random.randint(2, 3)):
                g.query(
                    """
                    MATCH (src:Account {id: $src}), (dst:Account {id: $dst})
                    CREATE (src)-[:TRANSACTED_WITH {id: $tx_id, amount: $amount, currency: 'USD',
                        timestamp: $ts, is_suspicious: true, channel: 'wire', pattern: 'layering'}]->(dst)
                    """,
                    {
                        "src": src,
                        "dst": dst,
                        "tx_id": f"TX_{_uid()}",
                        "amount": round(random.uniform(9000, 9999), 2),
                        "ts": (datetime.utcnow() - timedelta(days=random.randint(0, 20))).isoformat(),
                    },
                )

    # ── 4. Shared IP addresses (key fraud signal) ────────────────────────────
    for ring in fraud_rings:
        shared_ip = fake.ipv4()
        ip_node_id = f"IP_{shared_ip.replace('.', '_')}"
        g.query(
            """
            MERGE (ip:IPAddress {address: $addr, id: $id})
            """,
            {"addr": shared_ip, "id": ip_node_id},
        )
        for acc_id in ring:
            g.query(
                """
                MATCH (a:Account {id: $acc}), (ip:IPAddress {id: $ip})
                MERGE (a)-[:USES_IP]->(ip)
                """,
                {"acc": acc_id, "ip": ip_node_id},
            )

    # Also some legitimate accounts share IPs (shared WiFi etc)
    for _ in range(5):
        shared_ip = fake.ipv4()
        ip_node_id = f"IP_{shared_ip.replace('.', '_')}"
        g.query(
            "MERGE (ip:IPAddress {address: $addr, id: $id})",
            {"addr": shared_ip, "id": ip_node_id},
        )
        for acc_id in random.sample(legit_accounts, 2):
            g.query(
                """
                MATCH (a:Account {id: $acc}), (ip:IPAddress {id: $ip})
                MERGE (a)-[:USES_IP]->(ip)
                """,
                {"acc": acc_id, "ip": ip_node_id},
            )

    # ── 5. Devices (shared device fingerprints) ──────────────────────────────
    for ring in fraud_rings:
        fp = fake.md5()
        g.query(
            "MERGE (d:Device {fingerprint: $fp})",
            {"fp": fp},
        )
        for acc_id in random.sample(ring, min(3, len(ring))):
            g.query(
                """
                MATCH (a:Account {id: $acc}), (d:Device {fingerprint: $fp})
                MERGE (a)-[:USES_DEVICE]->(d)
                """,
                {"acc": acc_id, "fp": fp},
            )

    # ── 6. Entities (corporate ownership) ────────────────────────────────────
    for ring in fraud_rings:
        ent_id = f"ENT_{_uid()}"
        g.query(
            """
            MERGE (e:Entity {id: $id})
            SET e.name = $name, e.type = 'corporate', e.jurisdiction = $j
            """,
            {
                "id": ent_id,
                "name": f"Apex Ventures {fake.last_name()} LLC",
                "j": random.choice(["CY", "VG", "KY"]),
            },
        )
        # Shell owned by entity
        g.query(
            """
            MATCH (e:Entity {id: $ent}), (a:Account {id: $acc})
            MERGE (a)-[:OWNED_BY]->(e)
            """,
            {"ent": ent_id, "acc": ring[0]},
        )

    # ── 7. Alert events ──────────────────────────────────────────────────────
    for ring in fraud_rings:
        for acc_id in ring:
            alert_id = f"ALERT_{_uid()}"
            g.query(
                """
                MERGE (al:AlertEvent {id: $id})
                SET al.type = $type,
                    al.severity = $severity,
                    al.timestamp = $ts,
                    al.resolved = false
                WITH al
                MATCH (a:Account {id: $acc})
                MERGE (a)-[:HAS_ALERT]->(al)
                """,
                {
                    "id": alert_id,
                    "type": random.choice(
                        ["structuring", "rapid_movement", "layering", "smurfing"]
                    ),
                    "severity": random.choice(["HIGH", "CRITICAL"]),
                    "ts": datetime.utcnow().isoformat(),
                    "acc": acc_id,
                },
            )

    from tools import build_flow_projection
    seed_rapid_pass_throughs(g)
    build_flow_projection()

    print("✅ FraudScope graph seeded successfully!")
    print(f"   Accounts: {len(all_accounts)}")
    print(f"   Fraud rings: {len(fraud_rings)}")

    # Return summary for verification
    result = g.query("MATCH (n) RETURN labels(n) as label, count(n) as cnt")
    for row in result.result_set:
        print(f"   {row[0]}: {row[1]} nodes")


def seed_rapid_pass_throughs(g=None) -> int:
    """
    Seed realistic rapid mule relay pass-through sequences (< 30 minutes)
    for temporal velocity analysis and sliding window replay.
    """
    if g is None:
        g = get_graph()

    # Discover fraud rings
    rings: dict = {}
    res = g.query("MATCH (a:Account) WHERE a.ring_id IS NOT NULL RETURN a.ring_id, a.id, a.name, a.entity_type")
    for row in res.result_set:
        r_id, a_id, name, etype = row
        if r_id not in rings:
            rings[r_id] = {"shell": None, "mules": []}
        if etype == "shell_company":
            rings[r_id]["shell"] = a_id
        else:
            rings[r_id]["mules"].append(a_id)

    # Discover cashouts
    cash_res = g.query("MATCH (a:Account) WHERE a.entity_type = 'crypto_exchange' RETURN a.id")
    cashouts = [row[0] for row in cash_res.result_set]
    if not cashouts:
        cashout_id = f"CASHOUT_{_uid()}"
        g.query("""
            MERGE (a:Account {id: $id})
            SET a.name = 'Zenith Global Exchange', a.country = 'SC', a.balance = 2500000.0,
                a.risk_score = 0.45, a.is_suspicious = false, a.entity_type = 'crypto_exchange',
                a.created_at = $ts
        """, {"id": cashout_id, "ts": datetime.utcnow().isoformat()})
        cashouts.append(cashout_id)

    seeded_count = 0
    now = datetime.utcnow()

    for idx, (r_id, rdata) in enumerate(rings.items()):
        shell = rdata["shell"]
        mules = rdata["mules"]
        if not shell or len(mules) < 2:
            continue
        cashout = cashouts[idx % len(cashouts)]

        # Sequence 1: 3-hop high-velocity mule pass-through (all under 30 mins)
        # Shell -> Mule 1 -> Mule 2 -> Cashout
        base_time = now - timedelta(days=1, hours=(idx * 4 + 2), minutes=15)
        amt0 = round(random.uniform(9800, 9950), 2)
        amt1 = round(amt0 - random.uniform(180, 300), 2)
        amt2 = round(amt1 - random.uniform(150, 250), 2)

        t0 = base_time
        t1 = t0 + timedelta(minutes=random.randint(7, 12), seconds=random.randint(10, 45))
        t2 = t1 + timedelta(minutes=random.randint(9, 15), seconds=random.randint(10, 45))

        g.query("""
            MATCH (src:Account {id: $src}), (dst:Account {id: $dst})
            CREATE (src)-[:TRANSACTED_WITH {
                id: $tx_id, amount: $amount, currency: 'USD',
                timestamp: $ts, is_suspicious: true, channel: 'wire',
                pattern: 'rapid_pass_through'
            }]->(dst)
        """, {"src": shell, "dst": mules[0], "tx_id": f"TX_RAPID_{_uid()}", "amount": amt0, "ts": t0.isoformat()})

        g.query("""
            MATCH (src:Account {id: $src}), (dst:Account {id: $dst})
            CREATE (src)-[:TRANSACTED_WITH {
                id: $tx_id, amount: $amount, currency: 'wire',
                timestamp: $ts, is_suspicious: true, channel: 'wire',
                pattern: 'rapid_pass_through'
            }]->(dst)
        """, {"src": mules[0], "dst": mules[1], "tx_id": f"TX_RAPID_{_uid()}", "amount": amt1, "ts": t1.isoformat()})

        g.query("""
            MATCH (src:Account {id: $src}), (dst:Account {id: $dst})
            CREATE (src)-[:TRANSACTED_WITH {
                id: $tx_id, amount: $amount, currency: 'USDT',
                timestamp: $ts, is_suspicious: true, channel: 'crypto',
                pattern: 'rapid_pass_through'
            }]->(dst)
        """, {"src": mules[1], "dst": cashout, "tx_id": f"TX_RAPID_{_uid()}", "amount": amt2, "ts": t2.isoformat()})
        seeded_count += 3

        # Sequence 2: 2-hop rapid relay on secondary mules (e.g. 14 min turnaround)
        if len(mules) >= 4:
            base_time_b = now - timedelta(hours=(idx * 5 + 3), minutes=30)
            amt_b0 = round(random.uniform(9700, 9900), 2)
            amt_b1 = round(amt_b0 - random.uniform(150, 280), 2)
            tb0 = base_time_b
            tb1 = tb0 + timedelta(minutes=random.randint(8, 16), seconds=random.randint(5, 50))

            g.query("""
                MATCH (src:Account {id: $src}), (dst:Account {id: $dst})
                CREATE (src)-[:TRANSACTED_WITH {
                    id: $tx_id, amount: $amount, currency: 'USD',
                    timestamp: $ts, is_suspicious: true, channel: 'wire',
                    pattern: 'rapid_pass_through'
                }]->(dst)
            """, {"src": shell, "dst": mules[2], "tx_id": f"TX_RAPID_{_uid()}", "amount": amt_b0, "ts": tb0.isoformat()})

            g.query("""
                MATCH (src:Account {id: $src}), (dst:Account {id: $dst})
                CREATE (src)-[:TRANSACTED_WITH {
                    id: $tx_id, amount: $amount, currency: 'wire',
                    timestamp: $ts, is_suspicious: true, channel: 'wire',
                    pattern: 'rapid_pass_through'
                }]->(dst)
            """, {"src": mules[2], "dst": mules[3], "tx_id": f"TX_RAPID_{_uid()}", "amount": amt_b1, "ts": tb1.isoformat()})
            seeded_count += 2

    print(f"⚡ Seeded {seeded_count} rapid mule pass-through transactions!")
    return seeded_count


if __name__ == "__main__":
    seed_graph()
