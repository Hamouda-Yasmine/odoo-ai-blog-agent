# AI Blog Agent — Odoo 19 Module

Automated content discovery and SEO blog writing for Odoo 19 `website_blog`.  
The module implements a two-agent pipeline: a **Sniffer** that discovers trending topics, and a **Writer** that turns validated proposals into publication-ready blog posts.

---

## Features

| Feature | Description |
|---|---|
| Multi-domain monitoring | Each domain has its own keywords, language, news sources, and refresh frequency |
| Sniffer Agent | Fetches RSS / REST API sources or delegates to provider web search (Gemini Google Search) |
| Editorial validation | Proposals sit in a Kanban/list with Validate / Reject workflow before any writing starts |
| Writer Agent | Single-pass AI call producing title, subtitle, SEO meta fields, tags, HTML content, and cover image |
| Cover image | Upload a cover image on the proposal; the Writer sets it as the blog post background and OG image |
| Multi-provider | Configurable via URL / headers / body templates — works with Gemini, OpenAI, Claude, DeepSeek, or any compatible API |
| Cron automation | Sniffer runs on a configurable schedule per domain |
| Access control | Standalone "AI Blog Agent" category with User and Administrator groups |

---

## Module Structure

```
ai_blog_agent/
├── data/
│   ├── cron_data.xml          # Scheduled action for the Sniffer
│   ├── providers_data.xml     # Pre-configured providers (Gemini, OpenAI, Claude, DeepSeek)
│   └── sources_data.xml       # Sample RSS news sources
├── models/
│   ├── ai_blog_domain.py      # Domain + Sniffer agent logic
│   ├── ai_blog_keyword.py     # Keywords linked to a domain
│   ├── ai_blog_provider.py    # AI provider abstraction (URL/header/body templates)
│   ├── ai_blog_source.py      # News sources (RSS, REST API)
│   ├── ai_blog_proposal.py    # Proposal model + Writer agent logic
│   └── blog_post_extension.py # Adds proposal_id to blog.post
├── security/
│   ├── groups.xml             # Module category + User / Administrator groups
│   └── ir.model.access.csv   # Access rights per group
├── views/
│   ├── menu_views.xml
│   ├── ai_blog_domain_views.xml
│   ├── ai_blog_keyword_views.xml
│   ├── ai_blog_provider_views.xml
│   ├── ai_blog_source_views.xml
│   ├── ai_blog_proposal_views.xml
│   └── ai_blog_articles_views.xml
└── __manifest__.py
```

---

## Workflow

```
Configure domain  →  Add keywords & sources
        ↓
Sniffer runs (cron or manual button)
        ↓
Proposals created  →  Editor validates / rejects
        ↓
Writer generates article (AI single-pass)
        ↓
Editor reviews blog.post  →  Publish
```

---

## Configuration

### 1. AI Provider
Go to **AI Blog Agent → Configuration → AI Providers**.  
For each provider set:
- **API URL** — with `{model}` and `{api_key}` placeholders as needed
- **API Key**
- **Model** — e.g. `gemini-2.0-flash`, `gpt-4o-mini`
- **Request Headers** — JSON template, supports `{api_key}`
- **Request Body Template** — JSON template with `{prompt}`, `{model}`, `{max_tokens}`
- **Response Path** — dot-notation to the text field (e.g. `candidates.0.content.parts.0.text`)
- **Supports Web Search** — enable for Gemini to use Google Search instead of RSS sources

### 2. News Sources
Go to **AI Blog Agent → Configuration → News Sources**.  
Pre-loaded sources include Google News RSS. Add custom RSS feeds or REST APIs.

### 3. Domains
Go to **AI Blog Agent → Domains → Domains**.  
Each domain requires:
- A **name** and **language**
- At least one **keyword** (enforced on save)
- **News sources** (auto-selected; ignored when the provider has web search)
- **Frequency** (days between automatic Sniffer runs)

---

## Access Rights

| Group | Permissions |
|---|---|
| **User** | Read/write/create/delete proposals; read domains and keywords |
| **Administrator** | Full CRUD on all models; Domains, Keywords, Configuration menus; Run Sniffer button; API key field |

Assign groups in **Settings → Users → Access Rights → AI Blog Agent**.

---

## Dependencies

- `website_blog`
- `mail`

---

## Installation

```bash
# First install
odoo-bin -i ai_blog_agent -d <your_database>

# After any update
odoo-bin -u ai_blog_agent -d <your_database>
```

---

## License

LGPL-3 
