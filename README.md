# arXiv Digest

追踪 6 个 arXiv 分类的最新 AI/ML 论文，通过 arXiv 官方 API 抓取、SQLite 存储，由 Hermes cron job 编排三步隔离反思流水线（Draft → Critique → Refine）生成高质量中文摘要。

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│  Hermes Cron Jobs                                           │
│                                                             │
│  ┌─────────────────────┐    ┌─────────────────────────────┐ │
│  │ arXiv Fetch (2x/day)│    │ Daily Digest (1x/day 9pm)  │ │
│  │ 9:00 汇报            │    │                             │ │
│  │ 17:00 静默           │    │  script: digest query       │ │
│  │                     │    │       ↓ JSON 注入           │ │
│  │ script: arxiv_fetch │    │  Agent 编排 delegate_task   │ │
│  │       ↓             │    │       ↓                     │ │
│  │    SQLite DB        │    │  ┌──────────────────────┐   │ │
│  │ (6 分类 × 50 篇)    │    │  │ Subagent 1: Draft    │   │ │
│  └─────────────────────┘    │  │ (看得到原始论文)       │   │ │
│                             │  └──────────┬───────────┘   │ │
│                             │             ↓               │ │
│  ┌─────────────────────┐    │  ┌──────────────────────┐   │ │
│  │ arXiv API (免费)     │    │  │ Subagent 2: Critique │   │ │
│  │ 无需 API Key        │    │  │ (只看得到初稿，隔离) │   │ │
│  │ 请求间隔 3 秒       │    │  └──────────┬───────────┘   │ │
│  └─────────────────────┘    │             ↓               │ │
│                             │  ┌──────────────────────┐   │ │
│                             │  │ Subagent 3: Refine   │   │ │
│                             │  │ (初稿 + 审稿意见)    │   │ │
│                             │  └──────────┬───────────┘   │ │
│                             │             ↓               │ │
│                             │  ┌──────────────────────┐   │ │
│                             │  │ Step 4: Save Summary │   │ │
│                             │  │ (终稿写入 SQLite DB) │   │ │
│                             │  └──────────┬───────────┘   │ │
│                             │             ↓               │ │
│                             │     最终摘要 → Telegram     │ │
│                             └─────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## 文件结构

```
~/.hermes/hermes-agent/arxiv-digest/
├── db.py                  # 数据层：数据库 schema、连接、初始化
├── arxiv_fetch.py         # 抓取层：arXiv API 抓取、SQLite 存储、统计
├── arxiv_digest.py        # 查询层：查询、Focus Profile、订阅者管理
├── digest_generate.py     # 摘要层：数据加载 + 三步 Prompt 模板输出
├── data/
│   └── arxiv.db           # SQLite 数据库
└── README.md

~/.hermes/scripts/
├── arxiv_fetch.py         # Cron 包装：调用 arxiv_fetch.py fetch
└── arxiv_digest.py        # Cron 包装：调用 digest_generate.py query
```

## 追踪的内容

6 个 arXiv 分类，每个抓取 50 篇最新论文：

| 分类代码 | 名称 | 方向 |
|----------|------|------|
| cs.AI | Artificial Intelligence | 人工智能 |
| cs.LG | Machine Learning | 机器学习 |
| cs.CL | Computation and Language (NLP/LLM) | NLP / 大语言模型 |
| cs.CV | Computer Vision | 计算机视觉 |
| cs.MA | Multiagent Systems | 多智能体系统 |
| stat.ML | Statistics - Machine Learning | 统计机器学习 |

## 核心文件说明

### db.py

共享数据库模块。定义 schema、默认分类、默认 Focus Profile，提供 `get_db()` 和 `init_db()` 接口。

### arxiv_fetch.py

纯 Python 标准库，零外部依赖。通过 arXiv 官方 API 抓取论文，存入 SQLite。

**命令：**

| 命令 | 说明 |
|------|------|
| `fetch` | 抓取所有启用分类的最新论文，存入 DB |
| `fetch --report-hour H` | 指定 H 时只在该小时输出完整报告，其余时间静默存数据 |
| `stats [天数]` | 统计信息 |

**特性：**
- arXiv API 免费，无需 API Key
- 请求间隔 3 秒（遵守 arXiv 速率限制）
- paper_id 自动去重
- `--report-hour` 支持静默抓取（非报告时间只存数据不输出）

### arxiv_digest.py

查询、Focus Profile 管理、订阅者管理。

**命令：**

| 命令 | 说明 |
|------|------|
| `query [天数] [--category X] [--focus Z]` | 查询论文，输出 JSON |
| `save-summary [focus]` | 从 stdin 保存摘要到 DB |
| `focus-profiles` | 列出所有 Focus Profile |
| `add-focus <名> <JSON>` | 添加自定义 Focus Profile |
| `subscribers` | 列出订阅者 |
| `add-subscriber --email <email> [--name <name>] [--focus <focus>]` | 添加订阅者 |
| `remove-subscriber <email>` | 删除订阅者 |
| `toggle-subscriber <email>` | 启用/暂停订阅者 |

### digest_generate.py

数据加载 + 三步 Prompt 模板输出。不调用 LLM，LLM 调用由 Hermes cron agent 通过 delegate_task 完成。

**命令：**

| 命令 | 说明 |
|------|------|
| `query [--days 1] [--focus default]` | 输出论文数据 + 三步 Prompt 模板 JSON |
| `save-summary [--days 1] [--focus default]` | 从 stdin 保存摘要到 DB |
| `stats` | 简要统计 |

**query 输出 JSON 结构：**
```json
{
  "meta": { "date", "days", "focus", "focus_instructions", "total_papers", "focused_papers", "category_counts" },
  "papers": [ "按 focus 过滤后的论文列表（flat list）" ],
  "prompts": {
    "draft": "完整的初稿 Prompt（论文数据已嵌入）",
    "critique_template": "审稿模板（{draft} 占位符）",
    "refine_template": "精修模板（{draft} + {critique} 占位符）"
  }
}
```

## 三步隔离反思设计

核心思想：审稿人看不到原始数据，只能评估摘要质量。

| 步骤 | Subagent | 输入 | 输出 | 隔离 |
|------|----------|------|------|------|
| Draft | #1 | 原始论文 + 格式指令 | 初稿 | 看得到原始论文 |
| Critique | #2 | 只有初稿 | 审稿意见 + A/B/C 评分 | 看不到原始论文 |
| Refine | #3 | 初稿 + 审稿意见 | 终稿 | 看不到原始论文 |

每个 subagent 通过 Hermes `delegate_task` 创建，天然上下文隔离。

## Focus Profiles

控制摘要如何分配关注度。

| Profile | 重点分类 | 关键词 | 说明 |
|---------|---------|--------|------|
| default | 全部 | 无 | 均衡关注所有分类 |
| llm | cs.CL, cs.AI | language model, llm, transformer, rlhf... | 大语言模型方向 |
| agents | cs.AI, cs.MA, cs.CL | agent, multi-agent, tool use, planning... | AI Agent 方向 |
| vision | cs.CV | diffusion, image, video, 3d, generation... | 计算机视觉方向 |

自定义示例：
```bash
python3 arxiv_digest.py add-focus myprofile '{
  "categories": ["cs.CL", "cs.AI"],
  "keywords": ["reasoning", "chain-of-thought", "planning"],
  "instructions": "重点分析推理能力相关论文",
  "top_n": 15
}'
```

## 数据库结构

SQLite（`data/arxiv.db`），6 张表：

| 表 | 说明 |
|----|------|
| categories | 追踪的 arXiv 分类（code, name, enabled） |
| papers | 所有论文，按 paper_id 去重（title, authors, abstract, categories, url） |
| daily_entries | 每日抓取记录，关联 paper 和 category |
| summaries | 生成的摘要历史 |
| focus_profiles | Focus 配置 |
| subscribers | 订阅者 |

当前数据量：约 2292 篇论文，5000 条 daily_entries，13 份摘要。

## Cron Jobs

| Job | 时间 (PST) | 说明 |
|-----|-----------|------|
| arXiv Fetch | 9:00, 17:00 | 抓取 arXiv API，9 点发汇报，17 点静默 |
| arXiv Digest | 21:00 | 三步反思生成摘要（llm focus），保存到 DB，发送到 Telegram |

## 手动使用

```bash
cd ~/.hermes/hermes-agent/arxiv-digest

# 抓取最新论文
python3 arxiv_fetch.py fetch

# 查看统计
python3 arxiv_fetch.py stats 7
python3 digest_generate.py stats

# 查询 LLM 方向最近 3 天
python3 arxiv_digest.py query 3 --focus llm

# 查看特定分类
python3 arxiv_digest.py query 1 --category cs.CL

# 列出 Focus Profile
python3 arxiv_digest.py focus-profiles

# 列出订阅者
python3 arxiv_digest.py subscribers
```

## 迁移说明

从 OpenClaw workspace 迁移而来。主要改动：

- `digest_generate.py` 去掉了 OpenClaw Gateway API 调用，改为输出 JSON + Prompt 模板，LLM 调用由 Hermes delegate_task 完成
- Cron 脚本必须是 .py（Hermes scheduler 固定用 Python 解释器执行）
- Cron 脚本必须放在 `~/.hermes/scripts/`（路径校验限制）
- GitHub: https://github.com/brent-wei-liu/arxiv-digest

## 已知限制

- arXiv 周末不更新论文，周一抓取可能无新数据
- arXiv API 要求请求间隔 3 秒，6 个分类全抓一次约需 20 秒
- 三步 delegate_task 串行执行，生成摘要需要几分钟
- digest_generate.py query 输出较大（包含完整论文摘要数据）
- 纯 Python 标准库，无外部依赖
