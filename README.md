# time-machine-news

MCP server that lets Claude explore historical US newspapers from the Library of Congress.

It connects Claude to [Chronicling America](https://www.loc.gov/collections/chronicling-america/), the Library of Congress archive of more than 20 million digitized newspaper pages from the 1700s to 1963. Ask about a day, a town, or an event, and Claude searches the archive, reads the pages, and links back to each scan.

## Use the hosted version

Open **https://time-machine-news-alpha.vercel.app** and copy the connector link, or use it directly:

```
https://time-machine-news-alpha.vercel.app/mcp
```

1. In Claude, open **Settings**, then **Connectors**.
2. Choose **Add custom connector**, name it Time Machine News, paste the link, and select **Add**.
3. In a chat, open the tools menu below the message box and turn on Time Machine News.

No account or API key is needed. To add it to Claude Code instead:

```bash
claude mcp add --transport http time-machine-news https://time-machine-news-alpha.vercel.app/mcp
```

## Tools

| Tool | What it does |
| --- | --- |
| `search_newspapers` | Full-text search of page OCR, filtered by date range, state, newspaper (LCCN), and front pages only. |
| `front_pages_on_date` | Front pages printed on a given day, with their opening text. |
| `get_page_text` | Full OCR text of one page, in chunks, with a citation and links to the scan and PDF. |
| `find_newspapers` | Newspapers by name, state, or city, with their years in print and LCCN. |

Things to try: "What did Kansas newspapers report the week the Titanic sank?" or "Summarize the front pages from November 11, 1918."

## Run locally

Requires Python 3.10 or newer.

```bash
git clone https://github.com/ronakrupani/time-machine-news.git
cd time-machine-news
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

**Over stdio** (Claude Desktop, Claude Code). The `time-machine-news` command runs the server over stdio. For Claude Desktop, add this to `claude_desktop_config.json`, using the absolute path to your clone:

```json
{
  "mcpServers": {
    "time-machine-news": {
      "command": "/absolute/path/to/time-machine-news/.venv/bin/time-machine-news"
    }
  }
}
```

For Claude Code:

```bash
claude mcp add time-machine-news -- /absolute/path/to/time-machine-news/.venv/bin/time-machine-news
```

**Over HTTP** (the same app that runs on Vercel, including the landing page):

```bash
uvicorn time_machine_news.app:app --reload
```

The landing page is at http://localhost:8000 and the MCP endpoint at http://localhost:8000/mcp.

**Tests:**

```bash
pytest
```

The tests use recorded responses and never call loc.gov.

## Deploy your own

The project deploys to Vercel as-is: `pyproject.toml` sets the entrypoint (`[tool.vercel]`) and lists the dependencies.

```bash
vercel deploy --prod
```

The Library of Congress allows about 20 API requests per minute per client and blocks for an hour past that, so the server caches results and caps itself at 15 lookups a minute. Without Redis, each server instance keeps its own cache and counter. To share them across instances, add an [Upstash Redis](https://upstash.com) database (directly or through the Vercel Marketplace) and set these environment variables in Vercel (see `.env.example`):

```
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=
```

The Marketplace integration's `KV_REST_API_URL` and `KV_REST_API_TOKEN` names work too.

## Notes

- Page text is machine OCR of old microfilm and contains errors. Check the scan before quoting.
- Coverage ends in 1963; most pages are from 1836 to 1922.
- A new search can take up to a minute because loc.gov is slow on broad queries. Repeat searches come from the cache.
- Newspaper scans and text come from the Library of Congress. This project isn't affiliated with the Library.

## License

[MIT](LICENSE)
