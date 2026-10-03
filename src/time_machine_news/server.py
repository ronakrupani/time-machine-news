"""time-machine-news MCP server: lets Claude explore Chronicling America, the
Library of Congress archive of digitized US newspapers."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .loc import LocClient, LocError, Match

INSTRUCTIONS = """\
Time Machine News searches Chronicling America, the Library of Congress archive of
digitized US newspapers from the 1700s through 1963 (most coverage is 1836-1922).

- Start with search_newspapers or front_pages_on_date, then call get_page_text on a
  result's page_url to read the whole page.
- Keep searches narrow: a date range of days, weeks, or a few years, plus a state or
  newspaper when you can. Broad searches are slow (10-40 seconds) and can fail.
- The archive allows only a few lookups per minute for everyone using this server,
  so avoid issuing many searches in parallel.
- Page text is machine OCR of old microfilm and contains errors. Quote carefully,
  and give readers the page_url so they can check the original scan.
"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)

mcp = MCPServer(
    name="time-machine-news",
    title="Time Machine News",
    instructions=INSTRUCTIONS,
    website_url="https://github.com/ronakrupani/time-machine-news",
)


def _client() -> LocClient:
    return LocClient()


StartDate = Annotated[
    str | None,
    Field(description="Earliest publication date: YYYY, YYYY-MM, or YYYY-MM-DD."),
]
EndDate = Annotated[
    str | None,
    Field(description="Latest publication date: YYYY, YYYY-MM, or YYYY-MM-DD."),
]
State = Annotated[
    str | None,
    Field(description="US state or territory where the paper was published, e.g. 'Kansas' or 'KS'."),
]


@mcp.tool(title="Search newspaper pages", annotations=READ_ONLY)
async def search_newspapers(
    query: Annotated[str, Field(description="Words to find in the text of newspaper pages.")],
    start_date: StartDate = None,
    end_date: EndDate = None,
    state: State = None,
    newspaper_lccn: Annotated[
        str | None,
        Field(description="Limit to one newspaper by its LCCN, e.g. 'sn83030214' (from find_newspapers)."),
    ] = None,
    match: Annotated[
        Match,
        Field(description="'all' words (default), 'any' word, or the exact 'phrase'."),
    ] = "all",
    front_pages_only: Annotated[bool, Field(description="Only search front pages.")] = False,
    page: Annotated[int, Field(ge=1, le=100, description="Results page number.")] = 1,
    per_page: Annotated[int, Field(ge=1, le=25, description="Results per page.")] = 10,
) -> dict[str, Any]:
    """Search the full text of historical US newspaper pages (1700s-1963).

    Returns matching pages with the newspaper, date, place, a text snippet around the
    match, and a page_url to pass to get_page_text. Add a date range and a state or
    newspaper whenever possible; broad searches are slow.
    """
    try:
        return await _client().search_pages(
            query=query,
            start_date=start_date,
            end_date=end_date,
            state=state,
            lccn=newspaper_lccn,
            match=match,
            front_pages_only=front_pages_only,
            page=page,
            per_page=per_page,
        )
    except LocError as e:
        raise ToolError(str(e)) from None


@mcp.tool(title="Front pages for a date", annotations=READ_ONLY)
async def front_pages_on_date(
    date: Annotated[str, Field(description="Publication date, YYYY-MM-DD, e.g. '1912-04-16'.")],
    state: State = None,
    page: Annotated[int, Field(ge=1, le=100, description="Results page number.")] = 1,
    per_page: Annotated[int, Field(ge=1, le=25, description="Results per page.")] = 10,
) -> dict[str, Any]:
    """List newspaper front pages published on a specific day.

    Each result includes the opening text of the page (usually the top headlines) and a
    page_url for get_page_text. Good for "what was the news on <date>" questions.
    """
    if len(date.strip()) != 10:
        raise ToolError("date must be a single day in YYYY-MM-DD form.")
    try:
        return await _client().search_pages(
            start_date=date,
            end_date=date,
            state=state,
            front_pages_only=True,
            page=page,
            per_page=per_page,
        )
    except LocError as e:
        raise ToolError(str(e)) from None


@mcp.tool(title="Read a newspaper page", annotations=READ_ONLY)
async def get_page_text(
    page_url: Annotated[
        str,
        Field(
            description="A loc.gov page link from search results, "
            "e.g. https://www.loc.gov/resource/sn83030214/1912-04-16/ed-1/?sp=1"
        ),
    ],
    offset: Annotated[int, Field(ge=0, description="Character offset to start reading from, for long pages.")] = 0,
    max_chars: Annotated[int, Field(ge=1000, le=40000, description="Maximum characters of text to return.")] = 15000,
) -> dict[str, Any]:
    """Read the full OCR text of one newspaper page, with a citation and links to the scan and PDF.

    Long pages are returned in chunks: if `truncated` is true, call again with
    `offset` set to `next_offset`.
    """
    try:
        result = await _client().get_page(page_url)
    except LocError as e:
        raise ToolError(str(e)) from None
    text = result.pop("text")
    chunk = text[offset : offset + max_chars]
    end = offset + len(chunk)
    return {
        **result,
        "text": chunk if text else "No machine-readable text is available for this page.",
        "total_chars": len(text),
        "offset": offset,
        "truncated": end < len(text),
        "next_offset": end if end < len(text) else None,
    }


@mcp.tool(title="Find newspapers", annotations=READ_ONLY)
async def find_newspapers(
    name: Annotated[str | None, Field(description="Words from the newspaper's name, e.g. 'tribune'.")] = None,
    state: State = None,
    city: Annotated[str | None, Field(description="City of publication, e.g. 'Chicago'.")] = None,
    page: Annotated[int, Field(ge=1, le=100, description="Results page number.")] = 1,
    per_page: Annotated[int, Field(ge=1, le=50, description="Results per page.")] = 20,
) -> dict[str, Any]:
    """Find newspapers in the archive by name, state, or city.

    Returns each paper's title, years of publication, place, and LCCN (use it as
    newspaper_lccn in search_newspapers to search just that paper).
    """
    if not any(v and v.strip() for v in (name, state, city)):
        raise ToolError("Give at least one of name, state, or city.")
    try:
        return await _client().find_newspapers(name=name, state=state, city=city, page=page, per_page=per_page)
    except LocError as e:
        raise ToolError(str(e)) from None


def main():
    """Run over stdio, for local use with Claude Desktop or Claude Code."""
    mcp.run()


if __name__ == "__main__":
    main()
