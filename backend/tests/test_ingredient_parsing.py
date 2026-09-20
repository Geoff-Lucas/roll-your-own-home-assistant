from app.recipes.ingredient_parsing import parse_ingredient_line


def test_parses_quantity_and_name_from_a_real_line():
    result = parse_ingredient_line("2 cups all-purpose flour, sifted")

    assert result["raw_text"] == "2 cups all-purpose flour, sifted"
    assert "flour" in result["name"]
    assert result["quantity_text"] == "2 cups"


def test_falls_back_to_unparsed_on_failure(monkeypatch):
    import ingredient_parser

    def broken(_line):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(ingredient_parser, "parse_ingredient", broken)

    result = parse_ingredient_line("a pinch of salt")

    assert result == {"raw_text": "a pinch of salt", "name": "a pinch of salt", "quantity_text": None}
