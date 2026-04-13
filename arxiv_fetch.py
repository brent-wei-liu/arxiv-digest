#!/usr/bin/env python3
"""
arXiv Fetch — pull new papers from tracked categories via arXiv API.

Usage:
  python3 arxiv_fetch.py                    # Fetch new papers from all categories
  python3 arxiv_fetch.py --report-hour H    # Only report when local hour == H
  python3 arxiv_fetch.py stats [days]       # Quick stats
"""

import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
import urllib.request
import xml.etree.ElementTree as ET

from db import get_db, init_db

ARXIV_API = "http://export.arxiv.org/api/query"
MAX_RESULTS = 50  # per category
ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def fetch_category(category, max_results=MAX_RESULTS):
    """Fetch recent papers from a category via arXiv API."""
    url = f"{ARXIV_API}?search_query=cat:{category}&sortBy=submittedDate&sortOrder=descending&max_results={max_results}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "arXiv-Digest/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()

        root = ET.fromstring(content)
        papers = []

        for entry in root.findall(f"{ATOM_NS}entry"):
            paper_id_raw = entry.findtext(f"{ATOM_NS}id", "")
            # Extract arxiv ID: e.g., http://arxiv.org/abs/2403.12345v1 → 2403.12345
            paper_id = re.sub(r"v\d+$", "", paper_id_raw.split("/abs/")[-1]) if "/abs/" in paper_id_raw else paper_id_raw

            title = entry.findtext(f"{ATOM_NS}title", "").strip()
            title = re.sub(r"\s+", " ", title)  # collapse whitespace

            # Authors
            authors = []
            for author in entry.findall(f"{ATOM_NS}author"):
                name = author.findtext(f"{ATOM_NS}name", "").strip()
                if name:
                    authors.append(name)

            abstract = entry.findtext(f"{ATOM_NS}summary", "").strip()
            abstract = re.sub(r"\s+", " ", abstract)
            if len(abstract) > 1000:
                abstract = abstract[:1000] + "..."

            published = entry.findtext(f"{ATOM_NS}published", "")
            updated = entry.findtext(f"{ATOM_NS}updated", "")

            # Categories
            cats = []
            primary_cat = None
            for cat in entry.findall(f"{ATOM_NS}category"):
                term = cat.get("term", "")
                if term:
                    cats.append(term)
            primary_elem = entry.find(f"{ARXIV_NS}primary_category")
            if primary_elem is not None:
                primary_cat = primary_elem.get("term", "")

            # Links
            pdf_url = ""
            abs_url = ""
            for link in entry.findall(f"{ATOM_NS}link"):
                if link.get("title") == "pdf":
                    pdf_url = link.get("href", "")
                elif link.get("type") == "text/html":
                    abs_url = link.get("href", "")

            papers.append({
                "id": paper_id,
                "title": title,
                "authors": ", ".join(authors[:5]) + ("..." if len(authors) > 5 else ""),
                "abstract": abstract,
                "categories": ", ".join(cats),
                "primary_cat": primary_cat or category,
                "published": published,
                "updated": updated,
                "url": abs_url or f"https://arxiv.org/abs/{paper_id}",
                "pdf_url": pdf_url or f"https://arxiv.org/pdf/{paper_id}",
            })

        return {"status": "ok", "category": category, "papers": papers, "count": len(papers)}

    except Exception as e:
        return {"status": "failed", "category": category, "papers": [], "error": str(e)}


def cmd_fetch(conn, args=None):
    report_hour = None
    if args:
        for i, a in enumerate(args):
            if a == "--report-hour" and i + 1 < len(args):
                report_hour = int(args[i + 1])

    categories = conn.execute("SELECT code FROM categories WHERE enabled = 1").fetchall()
    now = datetime.now(timezone.utc).isoformat()
    stats = {"categories": {}, "new_papers": 0, "total_entries": 0, "dupes": 0, "failed": []}

    for cat_row in categories:
        cat = cat_row["code"]
        result = fetch_category(cat)

        if result["status"] == "ok":
            new = 0
            for p in result["papers"]:
                # Upsert paper
                existing = conn.execute("SELECT id FROM papers WHERE id = ?", (p["id"],)).fetchone()
                if not existing:
                    conn.execute(
                        """INSERT INTO papers (id, title, authors, abstract, categories, primary_cat,
                           published, updated, url, pdf_url, first_seen)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (p["id"], p["title"], p["authors"], p["abstract"], p["categories"],
                         p["primary_cat"], p["published"], p["updated"], p["url"], p["pdf_url"], now),
                    )
                    new += 1
                else:
                    stats["dupes"] += 1

                # Insert daily entry
                conn.execute(
                    "INSERT INTO daily_entries (paper_id, category, fetched_at) VALUES (?, ?, ?)",
                    (p["id"], cat, now),
                )

            stats["categories"][cat] = {"fetched": result["count"], "new": new}
            stats["new_papers"] += new
            stats["total_entries"] += result["count"]
        else:
            stats["failed"].append({"category": cat, "error": result.get("error", "unknown")})

        time.sleep(3)  # arXiv asks for 3-second delay between requests

    conn.commit()

    import zoneinfo
    local_hour = datetime.now(zoneinfo.ZoneInfo("America/Los_Angeles")).hour
    if report_hour is not None:
        stats["report"] = (local_hour == report_hour)
    else:
        stats["report"] = True

    print(json.dumps(stats, ensure_ascii=False, indent=2))


def cmd_stats(conn, args):
    days = int(args[0]) if args else 7
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    total_papers = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    recent_papers = conn.execute(
        "SELECT COUNT(DISTINCT paper_id) FROM daily_entries WHERE fetched_at >= ?", (cutoff,)
    ).fetchone()[0]

    by_cat = conn.execute(
        """SELECT category, COUNT(DISTINCT paper_id) as cnt
           FROM daily_entries WHERE fetched_at >= ?
           GROUP BY category ORDER BY cnt DESC""",
        (cutoff,),
    ).fetchall()

    print(f"📊 过去 {days} 天统计：")
    print(f"   总论文数（历史）：{total_papers}")
    print(f"   近期论文数：{recent_papers}")
    print(f"   按分类：")
    for r in by_cat:
        print(f"     {r['category']}: {r['cnt']} 篇")


def main():
    conn = get_db()
    init_db(conn)

    if len(sys.argv) < 2 or sys.argv[1] == "fetch":
        cmd_fetch(conn, sys.argv[1:] if len(sys.argv) > 1 else None)
    elif sys.argv[1] == "stats":
        cmd_stats(conn, sys.argv[2:])
    else:
        print(__doc__)
        sys.exit(1)

    conn.close()


if __name__ == "__main__":
    main()
