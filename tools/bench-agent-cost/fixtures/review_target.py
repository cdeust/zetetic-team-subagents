"""Synthetic fixture for the `review` bench task. Contains three deliberately
planted violations of rules/coding-standards.md, used only as a fixed
benchmark input — never imported or executed by production code."""

import requests


def process_order(order_id, db_conn):
    # Violation A: magic number (§3.1 — no magic numbers; discount threshold
    # has no name or source comment).
    row = db_conn.execute(f"SELECT total FROM orders WHERE id = {order_id}").fetchone()
    total = row[0]
    if total > 500:
        total = total * 0.9

    # Violation B: SRP — this function mixes I/O (HTTP call, DB read) with
    # business logic (discount calculation) in one function (§1.1, §3.1).
    resp = requests.post("https://payments.example.com/charge", json={"amount": total})
    if resp.status_code != 200:
        # Violation C: bare exception-free silent failure — error swallowed,
        # no named failure mode (coding-standards.md §9 anti-pattern list).
        return None

    db_conn.execute(f"UPDATE orders SET status='paid' WHERE id = {order_id}")
    return total
