# The GhostNet Company

42 Claude Code subagents, 7 departments, each agent bound to exactly one skill, existing to grow GhostNet — the real product described in `README.md`.

Every agent lives in `.claude/agents/<dept>-<skill>.md` and, as its first action, invokes its one bound skill via the `Skill` tool. Invoke any of them directly through the `Agent` tool using the `name` field below, or let a general-purpose session delegate to the right one by description.

**Provenance note:** only the Developers department's skills are real, third-party packages (installed from `claude-plugins-official`, `obra/superpowers`, and `Digital-Process-Tools/claude-remember`). The other 36 skill names came from screenshots of a product with no public marketplace entry anywhere on this machine — those `SKILL.md` files were authored from scratch with real, concrete methodology grounded in GhostNet's actual architecture, not fabricated as downloads. See each skill's `SKILL.md` for its content.

## 01 — Developers — *Ship code faster, from scaffold to QA*

| Agent | Skill | Source |
|---|---|---|
| `dev-superpowers` | `using-superpowers` (+13 sub-skills: brainstorming, systematic-debugging, TDD, plan writing/execution, code review, worktrees, etc.) | real — [obra/superpowers](https://github.com/obra/superpowers) |
| `dev-context7` | Context7 MCP server | real — Upstash Context7, via `claude-plugins-official` |
| `dev-mcp-builder` | `mcp-builder` | real — `mcp-server-dev` plugin, `claude-plugins-official` |
| `dev-skill-creator` | `skill-creator` | real — `claude-plugins-official` |
| `dev-webapp-testing` | Playwright MCP server | real — Microsoft Playwright, via `claude-plugins-official` |
| `dev-claude-mem` | `claude-mem` | real — [Digital-Process-Tools/claude-remember](https://github.com/Digital-Process-Tools/claude-remember) (skill only; hooks not installed) |

Context7 and Playwright are wired as project MCP servers in `.mcp.json`.

## 02 — Design — *UI that never looks templated*

`design-frontend-design` (real, pre-existing skill) · `design-web-artifacts` · `design-canvas-design` · `design-algorithmic-art` · `design-ui-ux-pro-max` · `design-slack-gif`

## 03 — Marketing — *Copy, SEO and ads that convert*

`marketing-seo-audit` · `marketing-programmatic-seo` · `marketing-ai-seo` · `marketing-cro` · `marketing-ad-creative` · `marketing-mktg-psychology`

## 04 — Social & Content — *Feed the algorithm on autopilot*

`content-social` · `content-copywriting` · `content-content-strategy` · `content-video` · `content-pillar-content` · `content-email-sequences`

## 05 — Finance — *Model the numbers before you spend*

`finance-dcf-model` · `finance-3-statements` · `finance-lbo-model` · `finance-comps-analysis` · `finance-pricing` · `finance-pitch-deck`

## 06 — Operations — *Run the business like a machine*

`ops-sop-builder` · `ops-incident-postmortem` · `ops-business-case` · `ops-launch-runbook` · `ops-internal-comms` · `ops-xlsx`

## 07 — Legal — *Read the fine print for you*

`legal-contract-review` · `legal-nda-triage` · `legal-legal-risk` · `legal-compliance` · `legal-docx` · `legal-sql-queries`

*(Legal agents are drafting/triage support, not licensed legal advice — `legal-risk` and `compliance` say so explicitly in their own methodology.)*

## Known gaps this company should probably pick up first

- `api_users.json` stores developer account passwords in plaintext (flagged, unresolved as of 2026-07-30) — natural first ticket for `legal-risk` + `dev-superpowers`.
- No `requirements.txt` was committed as of the last README pass — `ops-sop-builder` or `dev-superpowers` should close that.
- PR #1 (`worktree-ghostnet-scan-defense`) fixed the paid-API-doesn't-feed-the-ban-pipeline gap and the `ufw`-inactive enforcement gap — check its merge status before assuming either is live.
