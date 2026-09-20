import pytest

from app import geocoding


def test_us_places_show_city_and_state_without_the_country():
    payload = {
        "results": [
            {
                "name": "Fairfax",
                "admin1": "Virginia",
                "country": "United States",
                "country_code": "US",
                "latitude": 38.84622,
                "longitude": -77.30637,
            }
        ]
    }

    assert geocoding.to_candidates(payload) == [
        {"name": "Fairfax, Virginia", "latitude": 38.84622, "longitude": -77.30637}
    ]


def test_non_us_places_include_the_country():
    payload = {
        "results": [
            {
                "name": "London",
                "admin1": "England",
                "country": "United Kingdom",
                "country_code": "GB",
                "latitude": 51.5,
                "longitude": -0.12,
            }
        ]
    }

    assert geocoding.to_candidates(payload)[0]["name"] == "London, England, United Kingdom"


def test_state_is_not_repeated_when_it_matches_the_name():
    payload = {
        "results": [
            {
                "name": "Singapore",
                "admin1": "Singapore",
                "country": "Singapore",
                "country_code": "SG",
                "latitude": 1.3,
                "longitude": 103.8,
            }
        ]
    }

    assert geocoding.to_candidates(payload)[0]["name"] == "Singapore, Singapore"


def test_no_results_key_means_no_matches():
    # Open-Meteo omits "results" entirely rather than returning an empty list.
    assert geocoding.to_candidates({"generationtime_ms": 0.4}) == []


def test_results_without_coordinates_are_skipped():
    payload = {"results": [{"name": "Nowhere"}, {"name": "Somewhere", "latitude": 1.0, "longitude": 2.0}]}

    assert [c["name"] for c in geocoding.to_candidates(payload)] == ["Somewhere"]


@pytest.mark.anyio
async def test_short_queries_return_nothing_without_a_network_call(monkeypatch):
    def never_called(*args, **kwargs):
        raise AssertionError("should not hit the network for a too-short query")

    monkeypatch.setattr(geocoding.httpx, "AsyncClient", never_called)

    assert await geocoding.search_places(" a ") == []
