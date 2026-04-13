"""Shared database setup for arXiv Digest."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.environ.get(
    "ARXIV_DIGEST_DB_PATH",
    str(Path(__file__).resolve().parent / "data" / "arxiv.db"),
)

DEFAULT_CATEGORIES = [
    ("cs.AI", "Artificial Intelligence"),
    ("cs.LG", "Machine Learning"),
    ("cs.CL", "Computation and Language (NLP/LLM)"),
    ("cs.CV", "Computer Vision"),
    ("cs.MA", "Multiagent Systems"),
    ("stat.ML", "Statistics - Machine Learning"),
]

DEFAULT_FOCUS_PROFILES = [
    ("default", "All tracked categories", json.dumps({
        "categories": [],
        "keywords": [],
        "instructions": "",
        "top_n": 20
    })),
    ("llm", "LLM/NLP focused", json.dumps({
        "categories": ["cs.CL", "cs.AI"],
        "keywords": ["language model", "llm", "gpt", "claude", "transformer", "prompt", "fine-tune", "rlhf", "alignment", "reasoning", "chain-of-thought", "agent"],
        "instructions": "重点分析大语言模型相关论文，关注架构创新、训练方法和应用突破",
        "top_n": 20
    })),
    ("agents", "AI Agents focused", json.dumps({
        "categories": ["cs.AI", "cs.MA", "cs.CL"],
        "keywords": ["agent", "multi-agent", "tool use", "planning", "reasoning", "agentic", "autonomous", "self-play", "reward"],
        "instructions": "重点分析 AI Agent 相关论文，关注规划、工具使用、多智能体协作",
        "top_n": 20
    })),
    ("vision", "Computer Vision focused", json.dumps({
        "categories": ["cs.CV"],
        "keywords": ["diffusion", "image", "video", "3d", "generation", "detection", "segmentation", "world model"],
        "instructions": "重点分析计算机视觉论文，关注生成模型和视觉理解",
        "top_n": 20
    })),
]


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            code        TEXT PRIMARY KEY,
            name        TEXT,
            enabled     INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS papers (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            authors     TEXT,
            abstract    TEXT,
            categories  TEXT,
            primary_cat TEXT,
            published   TEXT,
            updated     TEXT,
            url         TEXT,
            pdf_url     TEXT,
            first_seen  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_entries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id    TEXT NOT NULL,
            category    TEXT NOT NULL,
            fetched_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS summaries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,
            focus       TEXT DEFAULT 'default',
            content     TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS focus_profiles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE NOT NULL,
            description TEXT,
            rules       TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS subscribers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT,
            email       TEXT UNIQUE,
            focus       TEXT DEFAULT 'default',
            enabled     INTEGER DEFAULT 1,
            created_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_daily_paper ON daily_entries(paper_id, fetched_at);
        CREATE INDEX IF NOT EXISTS idx_daily_cat ON daily_entries(category, fetched_at);
        CREATE INDEX IF NOT EXISTS idx_papers_published ON papers(published);
        CREATE INDEX IF NOT EXISTS idx_summaries_date ON summaries(date);
    """)

    if conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO categories (code, name) VALUES (?, ?)",
            DEFAULT_CATEGORIES,
        )

    if conn.execute("SELECT COUNT(*) FROM focus_profiles").fetchone()[0] == 0:
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT INTO focus_profiles (name, description, rules, created_at) VALUES (?, ?, ?, ?)",
            [(n, d, r, now) for n, d, r in DEFAULT_FOCUS_PROFILES],
        )

    conn.commit()
