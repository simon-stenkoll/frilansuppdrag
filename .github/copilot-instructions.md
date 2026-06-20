# GitHub Copilot Instructions

Behavioral guidelines derived from Andrej Karpathy's observations on LLM coding pitfalls.
These apply to all code in this repository.

---

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

- State assumptions explicitly; ask rather than guess
- If a requirement has multiple interpretations, name them and pick the most reasonable one — don't silently choose
- Push back when a simpler approach exists
- Stop when confused; name what's unclear rather than proceeding on a wrong assumption

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked
- No abstractions for single-use code
- No error handling for impossible scenarios
- No "flexibility" that wasn't requested
- If 200 lines could be 50, write 50

The test: Would a senior engineer say this is overcomplicated? If yes, simplify.

## 3. Surgical Changes

**Change only what is necessary. No collateral edits.**

- Do not refactor code adjacent to the thing being changed
- Do not rename variables or functions unless asked
- Do not adjust formatting, style, or comments in untouched code
- One PR, one purpose

## 4. Goal-Driven Execution

**Define what "done" looks like before writing code.**

- Every change should have a verifiable success criterion
- Prefer test-first thinking: what would prove this works?
- For multi-step tasks, verify each step before proceeding to the next

---

## Project Conventions

- **Language**: Python 3.11+
- **HTTP**: `httpx` (async) for scraping, `requests` for simple one-off calls
- **HTML parsing**: `BeautifulSoup4`
- **Scheduling**: GitHub Actions cron
- **LLM**: GitHub Models API (OpenAI-compatible SDK) — use `gpt-4o-mini`
- **Config**: `src/config.py` — all keywords, URLs, and settings live here
- **Scraper interface**: every scraper exposes `async def scrape() -> list[Assignment]`
- **Failures**: a scraper that raises an exception must be caught in the orchestrator; one failure must not stop the rest
- **Output**: `docs/index.html` (latest) + `docs/archive/YYYY-MM-DD.html`
- **State**: `state/seen.json` tracks previously seen assignment URLs
