import httpx
import pytest
from mcp import Client
from starlette.testclient import TestClient

from time_machine_news import server
from time_machine_news.app import app
from time_machine_news.cache import MemoryStore
from time_machine_news.loc import LocClient

from .sample_data import FULLTEXT_RESPONSE, RESOURCE_RESPONSE, SEARCH_RESPONSE

TOOLS = {"search_newspapers", "front_pages_on_date", "get_page_text", "find_newspapers"}


@pytest.fixture
def fake_loc(monkeypatch):
    def handler(request):
        if request.url.host == "tile.loc.gov":
            return httpx.Response(200, json=FULLTEXT_RESPONSE)
        if "/resource/" in request.url.path:
            return httpx.Response(200, json=RESOURCE_RESPONSE)
        return httpx.Response(200, json=SEARCH_RESPONSE)

    store = MemoryStore()
    monkeypatch.setattr(server, "_client", lambda: LocClient(store=store, transport=httpx.MockTransport(handler)))


@pytest.mark.anyio
async def test_tools_are_listed_as_read_only():
    async with Client(server.mcp) as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == TOOLS
    assert all(t.annotations.read_only_hint for t in tools)


@pytest.mark.anyio
async def test_search_tool(fake_loc):
    async with Client(server.mcp) as client:
        result = await client.call_tool("search_newspapers", {"query": "titanic", "state": "MT"})
    assert not result.is_error
    assert result.structured_content["results"][0]["newspaper"] == "The roundup record (Roundup, Mont.)"


@pytest.mark.anyio
async def test_get_page_text_chunks_long_text(fake_loc):
    url = "https://www.loc.gov/resource/sn86075094/1912-04-19/ed-1/?sp=2"
    async with Client(server.mcp) as client:
        first = (await client.call_tool("get_page_text", {"page_url": url, "max_chars": 1000})).structured_content
    assert first["truncated"] is False
    assert first["next_offset"] is None
    assert first["text"].startswith("Titanic Meets")


@pytest.mark.anyio
async def test_bad_input_returns_a_readable_error(fake_loc):
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_page_text", {"page_url": "https://example.com/x"})
    assert result.is_error
    assert "page_url must be" in result.content[0].text


@pytest.fixture(scope="module")
def http():
    # The app's lifespan (which starts the MCP session manager) runs once per
    # process, as it does on a real deploy, so share one client.
    with TestClient(app, base_url="https://time-machine-news.vercel.app") as client:
        yield client


def test_landing_page_shows_connector_url(http):
    response = http.get("/")
    assert response.status_code == 200
    assert 'value="https://time-machine-news.vercel.app/mcp"' in response.text


def test_mcp_endpoint_answers_over_http_on_any_host(http):
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    init = http.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
    )
    assert init.status_code == 200, init.text
    assert init.json()["result"]["serverInfo"]["name"] == "time-machine-news"

    listed = http.post(
        "/mcp",
        headers={**headers, "MCP-Protocol-Version": "2025-06-18"},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert listed.status_code == 200, listed.text
    assert {t["name"] for t in listed.json()["result"]["tools"]} == TOOLS
