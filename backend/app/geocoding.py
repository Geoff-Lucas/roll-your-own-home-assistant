import httpx

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
MAX_RESULTS = 8


def _label(result: dict) -> str:
    """"Fairfax, Virginia" for US places; the country is appended for
    everywhere else, since a bare "Paris, Texas"-style ambiguity is more
    common abroad than a reader can resolve from the state alone."""
    parts = [result["name"]]
    admin1 = result.get("admin1")
    if admin1 and admin1 != result["name"]:
        parts.append(admin1)
    country = result.get("country")
    if country and result.get("country_code") != "US":
        parts.append(country)
    return ", ".join(parts)


def to_candidates(payload: dict) -> list[dict]:
    """Open-Meteo returns no "results" key at all (not an empty list) when
    nothing matches."""
    return [
        {"name": _label(result), "latitude": result["latitude"], "longitude": result["longitude"]}
        for result in payload.get("results", [])
        if "latitude" in result and "longitude" in result
    ]


async def search_places(query: str) -> list[dict]:
    query = query.strip()
    if len(query) < 2:
        return []
    params = {"name": query, "count": MAX_RESULTS, "language": "en", "format": "json"}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(GEOCODING_URL, params=params)
        response.raise_for_status()
        return to_candidates(response.json())
