from app.recipes.ingredient_parsing import parse_ingredient_line


def test_parses_quantity_and_name_from_a_real_line():
    result = parse_ingredient_line("2 cups all-purpose flour, sifted")

    assert result["raw_text"] == "2 cups all-purpose flour, sifted"
    assert "flour" in result["name"]
    assert result["quantity_text"] == "2 cups"


def test_strips_stray_symbols_from_the_name():
    # Real line from an imported recipe: the "~" inside the parenthetical used
    # to leak into the name as "taco seasoning ~".
    result = parse_ingredient_line("1, 1 oz. packet taco seasoning (~2 Tbsp. seasoning )")

    assert result["name"] == "taco seasoning"
    assert result["quantity_text"] == "1 packet"


def test_keeps_the_unit_as_the_recipe_wrote_it():
    # The library re-pluralizes units by quantity ("3/4 cup" -> "3/4 cups",
    # "1 1/2 - 2 cups" -> "1 1/2-2 cup"); the original wording should win.
    assert parse_ingredient_line("3/4 cup water")["quantity_text"] == "3/4 cup"
    assert parse_ingredient_line("1 1/2 - 2 cups shredded Mexican cheese blend")["quantity_text"] == "1 1/2-2 cups"
    assert parse_ingredient_line("1 lb. ground beef, 80/20 or 90/10")["quantity_text"] == "1 lb"
    assert parse_ingredient_line("2 tablespoons olive oil")["quantity_text"] == "2 tablespoons"


def test_quantityless_label_line_is_kept_as_a_note_not_an_ingredient():
    line = "optional add-ins: guacamole, avocado, pickled jalapenos, refried beans."

    result = parse_ingredient_line(line)

    assert result == {"raw_text": line, "name": line, "quantity_text": None}


def test_falls_back_to_unparsed_on_failure(monkeypatch):
    import ingredient_parser

    def broken(_line):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(ingredient_parser, "parse_ingredient", broken)

    result = parse_ingredient_line("a pinch of salt")

    assert result == {"raw_text": "a pinch of salt", "name": "a pinch of salt", "quantity_text": None}
