#!/usr/bin/env python3
"""
arXiv Digest Generator — outputs paper data + 3-step prompt templates.

Designed for Hermes cron: outputs JSON to stdout, agent orchestrates
Draft → Critique → Refine via delegate_task.

Usage:
  python3 digest_generate.py query [--days 1] [--focus llm]
  python3 digest_generate.py save-summary [--days 1] [--focus default]  # stdin
  python3 digest_generate.py stats
"""

import json
import sys
from datetime import datetime, timezone, timedelta

from db import get_db, init_db


def cmd_query(conn, args):
    days = 1
    focus_name = "default"

    i = 0
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1]); i += 2
        elif args[i] == "--focus" and i + 1 < len(args):
            focus_name = args[i + 1]; i += 2
        else:
            i += 1

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Focus profile
    profile_row = conn.execute(
        "SELECT rules FROM focus_profiles WHERE name = ?", (focus_name,)
    ).fetchone()
    focus_rules = json.loads(profile_row["rules"]) if profile_row else {}
    focus_instructions = focus_rules.get("instructions", "")
    focus_categories = focus_rules.get("categories", [])
    keywords = focus_rules.get("keywords", [])
    top_n = focus_rules.get("top_n", 20)

    # Get papers
    sql = """
        SELECT DISTINCT p.id, p.title, p.authors, p.abstract, p.categories, p.primary_cat,
               p.published, p.url, p.pdf_url
        FROM daily_entries d
        JOIN papers p ON d.paper_id = p.id
        WHERE d.fetched_at >= ?
        ORDER BY p.published DESC
    """
    rows = conn.execute(sql, (cutoff,)).fetchall()

    papers = []
    for r in rows:
        papers.append({
            "id": r["id"],
            "title": r["title"],
            "authors": r["authors"],
            "abstract": r["abstract"][:300] if r["abstract"] else "",
            "categories": r["categories"],
            "primary_cat": r["primary_cat"],
            "published": r["published"],
            "url": r["url"],
            "pdf_url": r["pdf_url"],
        })

    # Filter by focus
    if focus_categories or keywords:
        def matches(p):
            if focus_categories:
                cats = (p["categories"] or "").lower()
                if any(c.lower() in cats for c in focus_categories):
                    return True
            if keywords:
                text = (p["title"] + " " + (p["abstract"] or "")).lower()
                if any(kw in text for kw in keywords):
                    return True
            return False
        focused = [p for p in papers if matches(p)]
        other = [p for p in papers if not matches(p)]
    else:
        focused = papers
        other = []

    # Category counts
    cat_counts = conn.execute(
        """SELECT d.category, COUNT(DISTINCT d.paper_id) as cnt
           FROM daily_entries d WHERE d.fetched_at >= ?
           GROUP BY d.category ORDER BY cnt DESC""",
        (cutoff,),
    ).fetchall()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Build paper text for prompts
    paper_lines = []
    for i_p, p in enumerate(focused[:top_n], 1):
        paper_lines.append(
            f"{i_p}. **{p['title']}**\n"
            f"   作者: {p['authors']}\n"
            f"   分类: {p['primary_cat']} | [论文]({p['url']})\n"
            f"   摘要: {p['abstract'][:200]}..."
        )

    if other and keywords:
        paper_lines.append(f"\n--- 其他论文（非 {focus_name} 重点）---")
        for i_p, p in enumerate(other[:5], len(focused[:top_n]) + 1):
            paper_lines.append(
                f"{i_p}. **{p['title']}** | {p['primary_cat']} | [链接]({p['url']})"
            )

    papers_text = "\n\n".join(paper_lines)
    cat_text = "\n".join(f"  - {r['category']}: {r['cnt']} 篇" for r in cat_counts)

    # 3-step prompts
    draft_prompt = f"""你是 arXiv 中文日报的撰稿人。请根据以下论文数据撰写一份精炼的中文摘要。

日期：{today}
Focus: {focus_name}
{f'Focus 说明：{focus_instructions}' if focus_instructions else ''}

## 分类统计
{cat_text}

## 今日重点论文

{papers_text}

## 要求

1. 用中文撰写，论文标题保留英文原文
2. 按研究方向分类（如 LLM/NLP、Agent、视觉、强化学习等）
3. 每条包含：标题（带 arXiv 链接）、作者、一段中文摘要（2-3 句话解释贡献和亮点）
4. 重点论文（方法创新或影响力大的）多写几句
5. 末尾加一段 "今日趋势"（2-3 句话总结研究动向）
6. 总长控制在 1000-1500 字"""

    critique_template = """你是一位资深 AI 研究员。请审阅以下 arXiv 中文日报初稿，给出改进建议。

## 初稿

{draft}

## 审稿要求

1. 论文摘要是否准确反映了原文贡献？有没有过度解读或遗漏关键点？
2. 分类是否合理？有没有更好的分组方式？
3. "今日趋势" 是否有洞察力？是否准确捕捉了研究方向？
4. 技术术语使用是否准确？
5. 有没有遗漏重要论文？

请按 A/B/C 评级：
- A：可以直接发布
- B：需要小幅修改
- C：需要大幅重写

给出具体修改建议。"""

    refine_template = """你是 arXiv 中文日报的终稿编辑。请根据审稿意见修改初稿，生成终稿。

## 初稿

{draft}

## 审稿意见

{critique}

## 要求

1. 根据审稿意见逐条修改
2. 保持原有格式和链接
3. 如果审稿评级为 A，只做微调
4. 如果评级为 B/C，按建议大幅修改
5. 终稿直接输出，不要包含修改说明"""

    output = {
        "meta": {
            "date": today,
            "days": days,
            "focus": focus_name,
            "focus_instructions": focus_instructions,
            "total_papers": len(papers),
            "focused_papers": len(focused),
            "category_counts": [dict(r) for r in cat_counts],
        },
        "papers": [p for p in focused[:top_n]],
        "prompts": {
            "draft": draft_prompt,
            "critique_template": critique_template,
            "refine_template": refine_template,
        },
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_save_summary(conn, args):
    content = sys.stdin.read().strip()
    if not content:
        print('{"error": "no content on stdin"}')
        return
    days = 1
    focus = "default"
    i = 0
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1]); i += 2
        elif args[i] == "--focus" and i + 1 < len(args):
            focus = args[i + 1]; i += 2
        else:
            i += 1

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO summaries (date, focus, content, created_at) VALUES (?, ?, ?, ?)",
        (today, focus, content, now),
    )
    conn.commit()
    print(json.dumps({"saved": True, "date": today, "focus": focus}))


def cmd_stats(conn):
    total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    entries = conn.execute("SELECT COUNT(*) FROM daily_entries").fetchone()[0]
    summaries = conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
    last_fetch = conn.execute(
        "SELECT MAX(fetched_at) FROM daily_entries"
    ).fetchone()[0]
    print(json.dumps({
        "total_papers": total,
        "total_entries": entries,
        "total_summaries": summaries,
        "last_fetch": last_fetch,
    }, indent=2))


def main():
    conn = get_db()
    init_db(conn)

    if len(sys.argv) < 2 or sys.argv[1] == "query":
        cmd_query(conn, sys.argv[2:] if len(sys.argv) > 2 else [])
    elif sys.argv[1] == "save-summary":
        cmd_save_summary(conn, sys.argv[2:])
    elif sys.argv[1] == "stats":
        cmd_stats(conn)
    else:
        print(__doc__)
        sys.exit(1)

    conn.close()


if __name__ == "__main__":
    main()
