"""Client for Chronicling America, the Library of Congress digitized newspaper archive.

Everything goes through the public loc.gov JSON API (no key needed). That API
allows about 20 requests a minute per client and blocks for an hour past that,
so results are cached and searches are throttled across all users of a deploy.
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import html
import json
import re
import time
from datetime import date
from typing import Any, Awaitable, Callable, Literal
from urllib.parse import urlparse

import httpx

from .cache import PREFIX, Store, get_store

COLLECTION_URL = "https://www.loc.gov/collections/chronicling-america/"
RESOURCE_URL = "https://www.loc.gov/resource/{lccn}/{date}/ed-{edition}/"
USER_AGENT = "time-machine-news/0.1 (+https://github.com/ronakrupani/time-machine-news)"

EARLIEST_DATE = "1756-01-01"
LATEST_DATE = "1963-12-31"

SEARCH_LIMIT_PER_MINUTE = 15  # Headroom under loc.gov's 20/minute.
COOLDOWN_SECONDS = 15 * 60
SEARCH_TTL = 7 * 24 * 3600
PAGE_TTL = 30 * 24 * 3600
TIMEOUT = httpx.Timeout(50.0, connect=10.0)
RETRY_DELAY = 1.5

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
TITLE_RE = re.compile(rf"^Image \d+ of (?P<paper>.+?), (?:{MONTHS}) \d{{1,2}}, \d{{4}}(?:, \((?P<edition>.+)\))?$")
PAGE_URL_RE = re.compile(r"^/resource/(?P<lccn>[a-z]{1,3}\d{8,10})/(?P<date>\d{4}-\d{2}-\d{2})/ed-(?P<edition>\d+)/?$")
SP_RE = re.compile(r"(?:^|&)sp=(\d+)")
LCCN_RE = re.compile(r"^[a-z]{1,3}\d{8,10}$")
YEARS_RE = re.compile(r"(\d{4})-(\d{4}|\d{2,3}\?|current)\s*$")

STATES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california",
    "CO": "colorado", "CT": "connecticut", "DE": "delaware", "DC": "district of columbia",
    "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho", "IL": "illinois",
    "IN": "indiana", "IA": "iowa", "KS": "kansas", "KY": "kentucky", "LA": "louisiana",
    "ME": "maine", "MD": "maryland", "MA": "massachusetts", "MI": "michigan", "MN": "minnesota",
    "MS": "mississippi", "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada",
    "NH": "new hampshire", "NJ": "new jersey", "NM": "new mexico", "NY": "new york",
    "NC": "north carolina", "ND": "north dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon",
    "PA": "pennsylvania", "PR": "puerto rico", "RI": "rhode island", "SC": "south carolina",
    "SD": "south dakota", "TN": "tennessee", "TX": "texas", "UT": "utah", "VT": "vermont",
    "VA": "virginia", "VI": "virgin islands", "WA": "washington", "WV": "west virginia",
    "WI": "wisconsin", "WY": "wyoming",
}

Match = Literal["all", "any", "phrase"]
OPS = {"all": "AND", "any": "OR", "phrase": "PHRASE"}


class LocError(Exception):
    """A failure worth explaining to the model: the message is shown as the tool result."""


# ---------- input normalization ----------


def normalize_state(state: str | None) -> str | None:
    if not state or not state.strip():
        return None
    value = state.strip()
    return STATES.get(value.upper(), value.lower())


def normalize_date(value: str | None, *, end: bool) -> str | None:
    """Accept YYYY, YYYY-MM, or YYYY-MM-DD and expand to a full date at the start or end of the period."""
    if not value or not value.strip():
        return None
    value = value.strip()
    try:
        if re.fullmatch(r"\d{4}", value):
            return f"{value}-12-31" if end else f"{value}-01-01"
        if re.fullmatch(r"\d{4}-\d{2}", value):
            year, month = map(int, value.split("-"))
            day = calendar.monthrange(year, month)[1] if end else 1
            return date(year, month, day).isoformat()
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise LocError(f"'{value}' isn't a valid date. Use YYYY, YYYY-MM, or YYYY-MM-DD.") from None


def date_range(start: str | None, end: str | None) -> tuple[str | None, str | None]:
    start_date = normalize_date(start, end=False)
    end_date = normalize_date(end, end=True)
    if start_date or end_date:
        start_date = start_date or EARLIEST_DATE
        end_date = end_date or LATEST_DATE
        if start_date > end_date:
            raise LocError(f"start_date ({start_date}) is after end_date ({end_date}).")
    return start_date, end_date


def normalize_lccn(lccn: str | None) -> str | None:
    if not lccn or not lccn.strip():
        return None
    value = lccn.strip().lower().replace(" ", "")
    if not LCCN_RE.match(value):
        raise LocError(f"'{lccn}' doesn't look like an LCCN (e.g. sn83030214). Use find_newspapers to look one up.")
    return value


def parse_page_url(page_url: str) -> tuple[str, str, int, int]:
    """Split a loc.gov newspaper page URL into (lccn, date, edition, page number)."""
    parsed = urlparse(page_url.strip())
    match = PAGE_URL_RE.match(parsed.path)
    if parsed.netloc not in ("www.loc.gov", "loc.gov") or not match:
        raise LocError(
            "page_url must be a loc.gov newspaper page link like "
            "https://www.loc.gov/resource/sn83030214/1912-04-16/ed-1/?sp=1 (use the page_url from search results)."
        )
    sp = SP_RE.search(parsed.query)
    return match["lccn"], match["date"], int(match["edition"]), int(sp.group(1)) if sp else 1


def page_url(lccn: str, date_str: str, edition: int, page: int) -> str:
    return RESOURCE_URL.format(lccn=lccn, date=date_str, edition=edition) + f"?sp={page}"


# ---------- response parsing ----------


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def snippet(text: str, query: str | None, width: int = 320) -> str:
    """A window of OCR text around the first query term, or the start of the page."""
    text = _squash(text)
    start = 0
    if query:
        for term in re.findall(r"\w+", query):
            found = text.lower().find(term.lower())
            if found >= 0:
                start = max(0, found - width // 3)
                break
    piece = text[start : start + width]
    return ("…" if start else "") + piece + ("…" if start + width < len(text) else "")


def best_image(urls: list[str] | None) -> str | None:
    images = [u.split("#")[0] for u in urls or [] if "/image-services/iiif/" in u]
    if not images:
        return None
    # IIIF lets us ask for a readable size instead of the thumbnail the API lists.
    return re.sub(r"/full/[^/]+/0/", "/full/1200,/0/", images[0])


def parse_page_result(result: dict[str, Any], query: str | None) -> dict[str, Any]:
    title = result.get("title") or ""
    match = TITLE_RE.match(title)
    paper = match["paper"] if match else (_first(result.get("partof_title")) or title).title()
    lccn = _first(result.get("number_lccn"))
    date_str = result.get("date")
    edition = int(_first(result.get("number_edition")) or 1)
    sp = SP_RE.search(urlparse(result.get("id") or "").query)
    page = int(sp.group(1)) if sp else int(_first(result.get("number_page")) or 1)
    return {
        "newspaper": paper,
        "date": date_str,
        "page": page,
        "edition": match["edition"] if match and match["edition"] else None,
        "city": (_first(result.get("location_city")) or "").title() or None,
        "state": (_first(result.get("location_state")) or "").title() or None,
        "lccn": lccn,
        "page_url": page_url(lccn, date_str, edition, page) if lccn and date_str else result.get("url"),
        "image_url": best_image(result.get("image_url")),
        "snippet": snippet(_first(result.get("description")) or "", query),
    }


def parse_title_result(result: dict[str, Any]) -> dict[str, Any]:
    title = result.get("title") or ""
    years = YEARS_RE.search(title)
    description = _first(result.get("description")) or ""
    return {
        "title": title,
        "lccn": _first(result.get("number_lccn")),
        "city": (_first(result.get("location_city")) or "").title() or None,
        "state": (_first(result.get("location_state")) or "").title() or None,
        "years": f"{years.group(1)}-{years.group(2)}" if years else result.get("date"),
        "description": description[:400] + ("…" if len(description) > 400 else ""),
        "url": result.get("url"),
    }


def clean_ocr(text: str) -> str:
    """Rejoin words split across lines and unwrap columns, keeping paragraph breaks."""
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    paragraphs = re.split(r"\n\s*\n", text)
    return "\n\n".join(p for p in (_squash(p) for p in paragraphs) if p)


def _strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


# ---------- client ----------


class LocClient:
    def __init__(self, store: Store | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.store = store or get_store()
        self.transport = transport

    async def _cached(self, key: str, ttl: int, produce: Callable[[], Awaitable[Any]]) -> Any:
        full_key = PREFIX + hashlib.sha256(key.encode()).hexdigest()[:32]
        cached = await self.store.get(full_key)
        if cached is not None:
            return json.loads(cached)
        value = await produce()
        await self.store.set(full_key, json.dumps(value), ttl)
        return value

    async def _check_limits(self) -> None:
        if await self.store.get(PREFIX + "cooldown"):
            raise LocError(
                "The Library of Congress is temporarily limiting requests from this server. Try again in about 15 minutes."
            )
        minute = int(time.time() // 60)
        count = await self.store.incr(f"{PREFIX}rl:{minute}", 90)
        if count > SEARCH_LIMIT_PER_MINUTE:
            wait = 60 - int(time.time() % 60)
            raise LocError(
                f"Too many Library of Congress lookups this minute; the archive only allows a few per minute. "
                f"Try again in {wait} seconds."
            )

    async def _get_json(self, url: str, params: dict[str, Any] | None = None, *, throttled: bool = True) -> Any:
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, transport=self.transport
            ) as client:
                for attempt in range(2):
                    if throttled:
                        await self._check_limits()
                    started = time.monotonic()
                    response = await client.get(url, params=params)
                    # loc.gov sometimes fails fast with a 5xx and then succeeds on retry;
                    # slow failures are usually overloaded searches, so don't repeat those.
                    if response.status_code < 500 or attempt or time.monotonic() - started > 10:
                        break
                    await asyncio.sleep(RETRY_DELAY)
        except httpx.TimeoutException:
            raise LocError(
                "The Library of Congress took too long to respond. Narrow the search "
                "(a shorter date range, a state, or a specific newspaper) and try again."
            ) from None
        except httpx.HTTPError:
            raise LocError("Couldn't reach the Library of Congress. Try again in a moment.") from None

        is_html = "text/html" in response.headers.get("content-type", "")
        if response.status_code == 429 or (response.status_code == 200 and is_html and throttled):
            # 429s and CAPTCHA pages mean loc.gov has started blocking; back off for everyone.
            await self.store.set(PREFIX + "cooldown", "1", COOLDOWN_SECONDS)
            raise LocError(
                "The Library of Congress is rate limiting requests right now. Try again in about 15 minutes."
            )
        if response.status_code == 404:
            raise LocError("The Library of Congress has no record at that address.")
        if response.status_code >= 500:
            raise LocError(
                f"The Library of Congress returned an error ({response.status_code}). This often happens with very "
                "broad searches: narrow the date range or add a state, then try again."
            )
        if response.status_code != 200:
            raise LocError(f"The Library of Congress returned an unexpected response ({response.status_code}).")
        try:
            return response.json()
        except ValueError:
            raise LocError("The Library of Congress returned a response that couldn't be read.") from None

    async def search_pages(
        self,
        query: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        state: str | None = None,
        lccn: str | None = None,
        match: Match = "all",
        front_pages_only: bool = False,
        page: int = 1,
        per_page: int = 10,
    ) -> dict[str, Any]:
        start, end = date_range(start_date, end_date)
        params: dict[str, Any] = {
            "dl": "page",
            "searchType": "advanced",
            "fo": "json",
            "at": "results,pagination",
            "c": per_page,
            "sp": page,
        }
        if query and query.strip():
            params["qs"] = query.strip()
            params["ops"] = OPS[match]
        if start and end:
            params["start_date"], params["end_date"] = start, end
        if state := normalize_state(state):
            params["location_state"] = state
        if lccn := normalize_lccn(lccn):
            params["fa"] = f"number_lccn:{lccn}"
        if front_pages_only:
            params["front_pages_only"] = "true"

        async def fetch() -> dict[str, Any]:
            data = await self._get_json(COLLECTION_URL, params)
            total = (data.get("pagination") or {}).get("of") or 0
            results = [parse_page_result(r, query) for r in data.get("results") or []]
            return {
                "total_results": total,
                "page": page,
                "per_page": per_page,
                "has_more": page * per_page < total,
                "results": results,
            }

        return await self._cached("search:" + json.dumps(params, sort_keys=True), SEARCH_TTL, fetch)

    async def find_newspapers(
        self,
        name: str | None = None,
        state: str | None = None,
        city: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"dl": "title", "fo": "json", "at": "results,pagination", "c": per_page, "sp": page}
        if name and name.strip():
            params["q"] = name.strip()
        facets = []
        if state := normalize_state(state):
            facets.append(f"location_state:{state}")
        if city and city.strip():
            facets.append(f"location_city:{city.strip().lower()}")
        if facets:
            params["fa"] = "|".join(facets)

        async def fetch() -> dict[str, Any]:
            data = await self._get_json(COLLECTION_URL, params)
            total = (data.get("pagination") or {}).get("of") or 0
            return {
                "total_results": total,
                "page": page,
                "per_page": per_page,
                "has_more": page * per_page < total,
                "newspapers": [parse_title_result(r) for r in data.get("results") or []],
            }

        return await self._cached("titles:" + json.dumps(params, sort_keys=True), SEARCH_TTL, fetch)

    async def get_page(self, url: str) -> dict[str, Any]:
        """Metadata and full OCR text for one newspaper page."""
        lccn, date_str, edition, sp = parse_page_url(url)
        canonical = page_url(lccn, date_str, edition, sp)

        async def fetch_meta() -> dict[str, Any]:
            data = await self._get_json(
                RESOURCE_URL.format(lccn=lccn, date=date_str, edition=edition),
                {"sp": sp, "fo": "json", "at": "resource,cite_this,pagination"},
            )
            resource = data.get("resource") or {}
            cite = data.get("cite_this") or {}
            paper = re.search(r"<cite>(.*?)</cite>", cite.get("chicago") or "")
            fulltext_url = resource.get("fulltext_file")
            return {
                "newspaper": _strip_tags(paper.group(1)) if paper else None,
                "pages_in_issue": (data.get("pagination") or {}).get("of"),
                "pdf_url": resource.get("pdf"),
                "image_url": _image_from_fulltext(fulltext_url) if fulltext_url else None,
                "fulltext_url": fulltext_url,
                "citation": _strip_tags(cite.get("chicago") or "") or None,
            }

        meta = await self._cached(f"page:{canonical}", PAGE_TTL, fetch_meta)
        fulltext_url = meta.pop("fulltext_url", None)

        async def fetch_text() -> str:
            if not fulltext_url or urlparse(fulltext_url).netloc != "tile.loc.gov":
                return ""
            data = await self._get_json(fulltext_url, throttled=False)
            segment = next(iter(data.values()), {}) if isinstance(data, dict) else {}
            return clean_ocr(segment.get("full_text") or "")

        text = await self._cached(f"text:{canonical}", PAGE_TTL, fetch_text)
        return {"date": date_str, "page": sp, "page_url": canonical, **meta, "text": text}


def _image_from_fulltext(fulltext_url: str) -> str | None:
    """Build this page's IIIF image URL from its text-service segment path.

    The resource's own `image` field can point at a neighbouring page's scan;
    the text segment path always names this page.
    """
    match = re.search(r"segment=/service/(.+?)\.xml", fulltext_url)
    if not match:
        return None
    identifier = match.group(1).replace("/", ":")
    return f"https://tile.loc.gov/image-services/iiif/service:{identifier}/full/1200,/0/default.jpg"
