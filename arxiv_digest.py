#!/usr/bin/env python3
"""
arXiv Digest — query, summarize, and manage subscribers.

Usage:
  python3 arxiv_digest.py query [days] [--category X] [--focus Z]
  python3 arxiv_digest.py save-summary [focus]       # Save summary from stdin
  python3 arxiv_digest.py focus-profiles              # List focus profiles
  python3 arxiv_digest.py add-focus <name> <json>     # Add a focus profile
  python3 arxiv_digest.py subscribers                 # List subscribers
  python3 arxiv_digest.py add-subscriber --email <email> [--name <name>] [--focus <focus>]
  python3 arxiv_digest.py remove-subscriber <email>
  python3 arxiv_digest.py toggle-subscriber <email>
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone, timedelta

from db import get_db, init_db


def cmd_query(conn, args):
    days = 1
    category_filter = None
    focus_name = "default"

    i = 0
    while i < len(args):
        if args[i] == "--category":
            category_filter = args[i + 1]; i += 2
        elif args[i] == "--focus":
            focus_name = args[i + 1]; i += 2
        elif args[i].isdigit():
            days = int(args[i]); i += 1
        else:
            i += 1

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    profile_row = conn.execute(
        "SELECT rules FROM focus_profiles WHERE name = ?", (focus_name,)
    ).fetchone()
    focus_rules = json.loads(profile_row["rules"]) if profile_row else {}

    where = ["d.fetched_at >= ?"]
    params = [cutoff]

    if category_filter:
        where.append("d.category = ?")
        params.append(category_filter)

    sql = f"""
        SELECT DISTINCT p.id, p.title, p.authors, p.abstract, p.categories, p.primary_cat,
               p.published, p.url, p.pdf_url
        FROM daily_entries d
        JOIN papers p ON d.paper_id = p.id
        WHERE {' AND '.join(where)}
        ORDER BY p.published DESC
    """
    rows = conn.execute(sql, params).fetchall()

    # Group by primary category
    by_cat = {}
    for r in rows:
        cat = r["primary_cat"] or "other"
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append({
            "id": r["id"],
            "title": r["title"],
            "authors": r["authors"],
            "abstract": r["abstract"],
            "categories": r["categories"],
            "published": r["published"],
            "url": r["url"],
            "pdf_url": r["pdf_url"],
        })

    # Category counts
    cat_counts = conn.execute(
        """SELECT d.category, COUNT(DISTINCT d.paper_id) as cnt
           FROM daily_entries d WHERE d.fetched_at >= ?
           GROUP BY d.category ORDER BY cnt DESC""",
        (cutoff,),
    ).fetchall()

    output = {
        "query": {
            "days_back": days,
            "cutoff": cutoff,
            "category_filter": category_filter,
            "focus": focus_name,
        },
        "focus_rules": focus_rules,
        "total_papers": len(rows),
        "category_counts": [dict(r) for r in cat_counts],
        "data": by_cat,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_save_summary(conn, args):
    content = sys.stdin.read().strip()
    if not content:
        print('{"error": "no content on stdin"}')
        return
    focus = args[0] if args else "default"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO summaries (date, focus, content, created_at) VALUES (?, ?, ?, ?)",
        (today, focus, content, now),
    )
    conn.commit()
    print(json.dumps({"saved": True, "date": today, "focus": focus}))


def cmd_focus_profiles(conn):
    rows = conn.execute("SELECT name, description, rules FROM focus_profiles ORDER BY name").fetchall()
    for r in rows:
        rules = json.loads(r["rules"])
        cats = ", ".join(rules.get("categories", [])) or "all"
        kw = ", ".join(rules.get("keywords", [])[:5]) or "none"
        print(f"  {r['name']}: {r['description']} (cats: {cats}, kw: {kw}...)")


def cmd_add_focus(conn, args):
    if len(args) < 2:
        print('Usage: add-focus <name> <json-rules>')
        return
    name, rules = args[0], args[1]
    now = datetime.now(timezone.utc).isoformat()
    try:
        json.loads(rules)
    except json.JSONDecodeError:
        print('{"error": "invalid JSON"}')
        return
    conn.execute(
        "INSERT OR REPLACE INTO focus_profiles (name, description, rules, created_at) VALUES (?, ?, ?, ?)",
        (name, "", rules, now),
    )
    conn.commit()
    print(json.dumps({"added": name}))


def cmd_subscribers(conn):
    rows = conn.execute(
        "SELECT name, email, focus, enabled FROM subscribers ORDER BY name"
    ).fetchall()
    if not rows:
        print("No subscribers yet. Use: add-subscriber --email <email> [--name <name>] [--focus <focus>]")
        return
    for r in rows:
        status = "✅" if r["enabled"] else "⏸️"
        name = r["name"] or "(no name)"
        print(f"  {status} {r['email']:35s}  {name:20s}  focus={r['focus']}")


def cmd_add_subscriber(conn, args):
    email = None
    name = None
    focus = "default"

    i = 0
    while i < len(args):
        if args[i] == "--email" and i + 1 < len(args):
            email = args[i + 1]; i += 2
        elif args[i] == "--name" and i + 1 < len(args):
            name = args[i + 1]; i += 2
        elif args[i] == "--focus" and i + 1 < len(args):
            focus = args[i + 1]; i += 2
        else:
            if not email and "@" in args[i]:
                email = args[i]
            i += 1

    if not email:
        print('Usage: add-subscriber --email <email> [--name <name>] [--focus <focus>]')
        return

    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO subscribers (name, email, focus, created_at) VALUES (?, ?, ?, ?)",
            (name, email, focus, now),
        )
        conn.commit()
        print(json.dumps({"added": email, "name": name, "focus": focus}))
    except sqlite3.IntegrityError:
        print(json.dumps({"error": f"{email} already subscribed"}))


def cmd_remove_subscriber(conn, args):
    if not args:
        print('Usage: remove-subscriber <email>')
        return
    conn.execute("DELETE FROM subscribers WHERE email = ?", (args[0],))
    conn.commit()
    print(json.dumps({"removed": args[0]}))


def cmd_toggle_subscriber(conn, args):
    if not args:
        print('Usage: toggle-subscriber <email>')
        return
    row = conn.execute("SELECT enabled FROM subscribers WHERE email = ?", (args[0],)).fetchone()
    if not row:
        print(json.dumps({"error": f"{args[0]} not found"}))
        return
    new_val = 0 if row["enabled"] else 1
    conn.execute("UPDATE subscribers SET enabled = ? WHERE email = ?", (new_val, args[0]))
    conn.commit()
    print(json.dumps({"email": args[0], "status": "enabled" if new_val else "disabled"}))


def main():
    conn = get_db()
    init_db(conn)

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "query": lambda: cmd_query(conn, args),
        "save-summary": lambda: cmd_save_summary(conn, args),
        "focus-profiles": lambda: cmd_focus_profiles(conn),
        "add-focus": lambda: cmd_add_focus(conn, args),
        "subscribers": lambda: cmd_subscribers(conn),
        "add-subscriber": lambda: cmd_add_subscriber(conn, args),
        "remove-subscriber": lambda: cmd_remove_subscriber(conn, args),
        "toggle-subscriber": lambda: cmd_toggle_subscriber(conn, args),
    }

    if cmd in commands:
        commands[cmd]()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)

    conn.close()


if __name__ == "__main__":
    main()
