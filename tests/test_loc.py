import json

import httpx
import pytest

from time_machine_news import loc
from time_machine_news.cache import PREFIX, MemoryStore
from time_machine_news.loc import LocClient, LocError

from .sample_data import FULLTEXT_RESPONSE, RESOURCE_RESPONSE, SEARCH_RESPONSE, TITLES_RESPONSE


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(loc, "RETRY_DELAY", 0)


def make_client(handler):
    requests = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return LocClient(store=MemoryStore(), transport=httpx.MockTransport(record)), requests


def test_normalize_state():
    assert loc.normalize_state("NY") == "new york"
    assert loc.normalize_state(" Kansas ") == "kansas"
    assert loc.normalize_state("") is None


def test_date_range_expands_partial_dates():
    assert loc.date_range("1918", "1918-02") == ("1918-01-01", "1918-02-28")
    assert loc.date_range("1912-04-15", None) == ("1912-04-15", loc.LATEST_DATE)
    assert loc.date_range(None, None) == (None, None)


def test_date_range_rejects_bad_input():
    with pytest.raises(LocError, match="isn't a valid date"):
        loc.date_range("April 1912", None)
    with pytest.raises(LocError, match="after end_date"):
        loc.date_range("1913", "1912")


def test_parse_page_url():
    assert loc.parse_page_url("https://www.loc.gov/resource/sn83030214/1912-04-16/ed-1/?sp=3&q=x") == (
        "sn83030214",
        "1912-04-16",
        1,
        3,
    )
    assert loc.parse_page_url("http://www.loc.gov/resource/sn83030214/1912-04-16/ed-2/")[2:] == (2, 1)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/resource/sn83030214/1912-04-16/ed-1/?sp=1",
        "https://www.loc.gov/item/sn83030214/",
        "not a url",
    ],
)
def test_parse_page_url_rejects_other_urls(url):
    with pytest.raises(LocError, match="page_url must be"):
        loc.parse_page_url(url)


def test_parse_page_result():
    result = loc.parse_page_result(SEARCH_RESPONSE["results"][0], "titanic")
    assert result["newspaper"] == "The roundup record (Roundup, Mont.)"
    assert result["date"] == "1912-04-19"
    assert result["page"] == 2
    assert result["state"] == "Montana"
    assert result["city"] == "Roundup"
    assert result["page_url"] == "https://www.loc.gov/resource/sn86075094/1912-04-19/ed-1/?sp=2"
    assert result["image_url"].endswith("/full/1200,/0/default.jpg")
    assert result["snippet"].startswith("Titanic Meets")

    extra = loc.parse_page_result(SEARCH_RESPONSE["results"][1], None)
    assert extra["newspaper"] == "Atlanta Georgian (Atlanta, Ga.)"
    assert extra["edition"] == "EXTRA"
    assert extra["image_url"] is None


def test_snippet_centers_on_query():
    text = "x " * 300 + "the TITANIC sank " + "y " * 300
    piece = loc.snippet(text, "titanic", width=100)
    assert "TITANIC" in piece
    assert piece.startswith("…") and piece.endswith("…")


def test_clean_ocr_rejoins_lines():
    text = FULLTEXT_RESPONSE[next(iter(FULLTEXT_RESPONSE))]["full_text"]
    assert loc.clean_ocr(text) == (
        "Titanic Meets Terrible Disaster-1350 Lives Lost\n\n"
        "Sinking of Titanic, world's greatest vessel, on maiden voyage across At lantic."
    )


@pytest.mark.anyio
async def test_search_pages_builds_query_and_caches():
    client, requests = make_client(lambda r: httpx.Response(200, json=SEARCH_RESPONSE))
    kwargs = dict(query="titanic", start_date="1912-04-15", end_date="1912-04-20", state="NY", per_page=2)

    first = await client.search_pages(**kwargs)
    second = await client.search_pages(**kwargs)

    assert first == second
    assert len(requests) == 1
    params = requests[0].url.params
    assert params["searchType"] == "advanced"
    assert params["dl"] == "page"
    assert params["qs"] == "titanic"
    assert params["ops"] == "AND"
    assert params["start_date"] == "1912-04-15"
    assert params["end_date"] == "1912-04-20"
    assert params["location_state"] == "new york"
    assert first["total_results"] == 191
    assert first["has_more"] is True
    assert len(first["results"]) == 2


@pytest.mark.anyio
async def test_front_page_search_has_no_query():
    client, requests = make_client(lambda r: httpx.Response(200, json=SEARCH_RESPONSE))
    await client.search_pages(start_date="1912-04-16", end_date="1912-04-16", front_pages_only=True)
    params = requests[0].url.params
    assert "qs" not in params
    assert params["front_pages_only"] == "true"


@pytest.mark.anyio
async def test_find_newspapers_combines_facets():
    client, requests = make_client(lambda r: httpx.Response(200, json=TITLES_RESPONSE))
    result = await client.find_newspapers(name="tribune", state="MT", city="Great Falls")
    params = requests[0].url.params
    assert params["dl"] == "title"
    assert params["q"] == "tribune"
    assert params["fa"] == "location_state:montana|location_city:great falls"
    assert result["newspapers"][0] == {
        "title": "Great Falls Daily Tribune (Great Falls, Mont.) 1895-1921",
        "lccn": "sn85042379",
        "city": "Great Falls",
        "state": "Montana",
        "years": "1895-1921",
        "description": "Daily",
        "url": "https://www.loc.gov/item/sn85042379/",
    }


@pytest.mark.anyio
async def test_get_page_fetches_metadata_then_text():
    def handler(request):
        if request.url.host == "www.loc.gov":
            return httpx.Response(200, json=RESOURCE_RESPONSE)
        return httpx.Response(200, json=FULLTEXT_RESPONSE)

    client, requests = make_client(handler)
    page = await client.get_page("https://www.loc.gov/resource/sn86075094/1912-04-19/ed-1/?sp=2&q=titanic")

    assert [r.url.host for r in requests] == ["www.loc.gov", "tile.loc.gov"]
    assert requests[0].url.params["sp"] == "2"
    assert page["newspaper"] == "The Roundup Record"
    assert page["pages_in_issue"] == 8
    assert page["page_url"] == "https://www.loc.gov/resource/sn86075094/1912-04-19/ed-1/?sp=2"
    # Built from this page's text segment (0135), not the resource thumbnail (0134).
    assert ":0135/full/1200,/0/default.jpg" in page["image_url"]
    assert page["citation"].startswith("The Roundup Record. (Roundup, MT)")
    assert page["text"].startswith("Titanic Meets Terrible")


@pytest.mark.anyio
async def test_rate_limit_stops_requests_before_loc_does(monkeypatch):
    monkeypatch.setattr(loc, "SEARCH_LIMIT_PER_MINUTE", 2)
    client, requests = make_client(lambda r: httpx.Response(200, json=SEARCH_RESPONSE))
    await client.search_pages(query="a")
    await client.search_pages(query="b")
    with pytest.raises(LocError, match="Too many"):
        await client.search_pages(query="c")
    assert len(requests) == 2


@pytest.mark.anyio
async def test_429_starts_a_cooldown_for_everyone():
    client, requests = make_client(lambda r: httpx.Response(429))
    with pytest.raises(LocError, match="rate limiting"):
        await client.search_pages(query="titanic")
    assert await client.store.get(PREFIX + "cooldown") == "1"
    with pytest.raises(LocError, match="temporarily limiting"):
        await client.search_pages(query="other")
    assert len(requests) == 1


@pytest.mark.anyio
async def test_captcha_page_counts_as_rate_limit():
    client, _ = make_client(lambda r: httpx.Response(200, html="<html>captcha</html>"))
    with pytest.raises(LocError, match="rate limiting"):
        await client.search_pages(query="titanic")


@pytest.mark.anyio
async def test_server_error_is_explained_after_one_retry():
    client, requests = make_client(lambda r: httpx.Response(503))
    with pytest.raises(LocError, match=r"error \(503\)"):
        await client.search_pages(query="titanic")
    assert len(requests) == 2


@pytest.mark.anyio
async def test_fast_server_error_is_retried():
    responses = iter([httpx.Response(500), httpx.Response(200, json=SEARCH_RESPONSE)])
    client, requests = make_client(lambda r: next(responses))
    result = await client.search_pages(query="titanic")
    assert result["total_results"] == 191
    assert len(requests) == 2


@pytest.mark.anyio
async def test_timeout_is_explained():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    client, _ = make_client(handler)
    with pytest.raises(LocError, match="took too long"):
        await client.search_pages(query="titanic")


@pytest.mark.anyio
async def test_errors_are_not_cached():
    responses = iter([httpx.Response(503), httpx.Response(503), httpx.Response(200, json=SEARCH_RESPONSE)])
    client, requests = make_client(lambda r: next(responses))
    with pytest.raises(LocError):
        await client.search_pages(query="titanic")
    result = await client.search_pages(query="titanic")
    assert result["total_results"] == 191
    assert len(requests) == 3


@pytest.mark.anyio
async def test_memory_store_expires(monkeypatch):
    store = MemoryStore()
    await store.set("k", json.dumps(1), ttl=10)
    assert await store.get("k") == "1"
    now = loc.time.time()
    monkeypatch.setattr("time_machine_news.cache.time.time", lambda: now + 11)
    assert await store.get("k") is None
