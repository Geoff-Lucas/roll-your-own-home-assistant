import pytest

from app.browser.urls import SEARCH_URL, is_web_url, normalize_address


def test_full_urls_pass_through_untouched():
    assert normalize_address("https://www.allrecipes.com/recipe/123/x/") == "https://www.allrecipes.com/recipe/123/x/"
    assert normalize_address("http://example.com") == "http://example.com"


def test_surrounding_whitespace_is_ignored():
    assert normalize_address("  https://example.com  ") == "https://example.com"


def test_bare_hostnames_get_https():
    assert normalize_address("example.com") == "https://example.com"
    assert normalize_address("www.seriouseats.com/recipes") == "https://www.seriouseats.com/recipes"
    assert normalize_address("recipes.example.co.uk") == "https://recipes.example.co.uk"


def test_a_hostname_with_a_port_is_a_host_not_a_scheme():
    # urlparse would read "localhost:8000" as scheme="localhost".
    assert normalize_address("example.com:8080/x") == "https://example.com:8080/x"


def test_anything_else_becomes_a_search():
    assert normalize_address("easy chicken soup") == SEARCH_URL + "easy+chicken+soup"
    assert normalize_address("mac & cheese") == SEARCH_URL + "mac+%26+cheese"


def test_terms_that_merely_contain_a_dot_are_still_searches_when_spaced():
    assert normalize_address("1.5 cups flour to grams") == SEARCH_URL + "1.5+cups+flour+to+grams"


@pytest.mark.parametrize(
    "hostile",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:text/html,<script>1</script>",
        "chrome://settings",
        "about:blank",
        "view-source:https://example.com",
        "ftp://example.com/file",
        "JAVASCRIPT:alert(1)",
    ],
)
def test_non_http_schemes_are_rejected(hostile):
    with pytest.raises(ValueError, match="http"):
        normalize_address(hostile)


@pytest.mark.parametrize("empty", ["", "   ", "\n"])
def test_empty_input_is_rejected(empty):
    with pytest.raises(ValueError):
        normalize_address(empty)


def test_is_web_url():
    assert is_web_url("https://example.com/recipe")
    assert is_web_url("http://example.com")
    assert not is_web_url("chrome://newtab")
    assert not is_web_url("about:blank")
    assert not is_web_url("")
    assert not is_web_url(None)
