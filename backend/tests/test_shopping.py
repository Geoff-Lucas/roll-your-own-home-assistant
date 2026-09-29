from fractions import Fraction
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
import segno

from app.shopping import MAILTO_LIMIT, build_lines, build_mailto, format_amount, is_staple, list_entries, normalize_name, parse_quantity


def ingredient(name, quantity=None):
    return {"raw_text": f"{quantity or ''} {name}".strip(), "name": name, "quantity_text": quantity}


def lines(*meals):
    """{name: (quantity, recipes)} for meals given as (title, [ingredients])."""
    return {line.name: (line.quantity, line.recipes) for line in build_lines(meals)}


# --- reading an amount -------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1 1/2 lb", (Fraction(3, 2), "lb")),
        ("3/4 cup", (Fraction(3, 4), "cup")),
        ("2", (Fraction(2), "")),
        ("0.5 cup", (Fraction(1, 2), "cup")),
        ("2 tablespoons", (Fraction(2), "tbsp")),
        ("1 Tbsp.", (Fraction(1), "tbsp")),
        ("3 cloves", (Fraction(3), "clove")),
        ("2 cans", (Fraction(2), "can")),
        ("1 bunch", (Fraction(1), "bunch")),
    ],
)
def test_parse_quantity(text, expected):
    assert parse_quantity(text) == expected


@pytest.mark.parametrize(
    "text", [None, "", "  ", "a handful", "a pinch", "1 1/2-2 cups", "2 to 3 cups", "1-2", "2 cans (15 oz)", "1 (8 oz) package"]
)
def test_amounts_that_cannot_be_added_up_are_not_guessed_at(text):
    assert parse_quantity(text) == (None, "")


def test_amounts_are_written_the_way_a_cook_reads_them():
    assert [format_amount(Fraction(n, d)) for n, d in [(5, 2), (1, 2), (3, 1), (7, 4), (1, 3)]] == ["2 1/2", "1/2", "3", "1 3/4", "1/3"]


def test_names_meet_whatever_the_plural_or_case():
    assert normalize_name("Carrots") == normalize_name("carrot")
    assert normalize_name("tomatoes") == normalize_name("Tomato")
    assert normalize_name("eggs") == normalize_name("egg")
    assert normalize_name("baby carrots") != normalize_name("carrots")
    assert normalize_name("olive oil, extra virgin") == "olive oil extra virgin"


# --- putting recipes together ------------------------------------------------


def test_the_same_ingredient_in_two_recipes_is_one_line_with_the_amounts_added():
    result = lines(
        ("Pot roast", [ingredient("yellow onion", "1"), ingredient("chuck roast", "3 lb")]),
        ("Beef chili", [ingredient("yellow onion", "2"), ingredient("ground beef", "1 1/2 lb")]),
    )

    assert result["yellow onion"] == ("3", ["Pot roast", "Beef chili"])
    assert result["chuck roast"] == ("3 lb", ["Pot roast"])


def test_amounts_in_the_same_unit_add_up_however_the_unit_is_written():
    result = lines(
        ("A", [ingredient("olive oil", "1 tbsp")]),
        ("B", [ingredient("olive oil", "2 tablespoons")]),
        ("C", [ingredient("chicken breast", "1 1/2 lb")]),
        ("D", [ingredient("Chicken breast", "1 lb")]),
    )

    assert result["olive oil"][0] == "3 tbsp"
    assert result["chicken breast"][0] == "2 1/2 lb"


def test_units_are_pluralized_by_the_total_not_by_the_first_recipe():
    result = lines(("A", [ingredient("black beans", "1 can")]), ("B", [ingredient("black beans", "1 can")]), ("C", [ingredient("garlic", "1 clove")]))

    assert result["black beans"][0] == "2 cans"
    assert result["garlic"][0] == "1 clove"


def test_different_units_are_listed_side_by_side_not_converted():
    result = lines(("A", [ingredient("milk", "1 cup")]), ("B", [ingredient("milk", "2 tbsp")]))

    assert result["milk"][0] == "1 cup + 2 tbsp"


def test_a_range_is_kept_as_written_and_not_added_to():
    result = lines(("A", [ingredient("cheese", "1 1/2-2 cups")]), ("B", [ingredient("cheese", "1 cup")]))

    assert result["cheese"][0] == "1 cup + 1 1/2-2 cups"


def test_a_size_note_in_the_amount_is_shown_as_written_not_mangled():
    result = lines(("A", [ingredient("kidney beans", "2 cans (15 oz)")]), ("B", [ingredient("kidney beans", "1 can (28 oz)")]))

    assert result["kidney beans"][0] == "2 cans (15 oz) + 1 can (28 oz)"


def test_an_ingredient_with_no_amount_is_still_on_the_list():
    result = lines(("A", [ingredient("salt pepper")]), ("B", [ingredient("salt pepper")]))

    assert result["salt pepper"] == ("", ["A", "B"])


def test_a_recipe_planned_twice_counts_twice_but_is_named_once():
    beans = ("Burrito bowls", [ingredient("black beans", "1 can")])

    result = lines(beans, beans)

    assert result["black beans"] == ("2 cans", ["Burrito bowls"])


def test_lines_come_out_in_alphabetical_order():
    result = build_lines([("A", [ingredient("zucchini", "1"), ingredient("apples", "2"), ingredient("milk", "1 cup")])])

    assert [line.name for line in result] == ["apples", "milk", "zucchini"]


def test_a_line_the_parser_could_not_split_still_lands_on_the_list_by_its_text():
    # parse_ingredient_line falls back to name = the whole line, no quantity.
    result = lines(("A", [{"raw_text": "a pinch of salt", "name": "a pinch of salt", "quantity_text": None}]))

    assert result == {"a pinch of salt": ("", ["A"])}


def test_older_recipes_without_the_structured_fields_and_empty_lines_do_not_break_it():
    result = lines(("A", [{"raw_text": "2 cups flour"}, {"raw_text": "", "name": ""}, ingredient("sugar", "1 cup")]), ("B", []))

    assert set(result) == {"2 cups flour", "sugar"}
    assert build_lines([("A", None)]) == []


# --- sending the list to a phone ---------------------------------------------


def opened(link):
    """What a phone's email app would show for a mailto: link: (to, subject, body)."""
    parts = urlsplit(link)
    query = parse_qs(parts.query)
    return unquote(parts.path), query["subject"][0], query["body"][0]


def test_entries_read_like_a_list_you_would_write():
    entries = list_entries([("chicken breast", "1 1/2 lb"), ("paper towels", ""), ("Eggs", "2")])

    assert entries == ["- Chicken breast: 1 1/2 lb", "- Paper towels", "- Eggs: 2"]


def test_the_link_opens_an_email_with_the_whole_list_in_it():
    entries = list_entries([("chicken breast", "1 1/2 lb & more"), ("crème fraîche", "1 cup"), ("milk", "")])

    link, included = build_mailto(entries, "Shopping list, Sep 28 - Oct 3", "me@example.com")

    to, subject, body = opened(link)
    assert (to, subject, included) == ("me@example.com", "Shopping list", 3)
    assert body == "Shopping list, Sep 28 - Oct 3\n\n" + "\n".join(entries)  # nothing lost to the encoding


def test_with_no_address_the_phone_is_left_to_ask():
    link, _ = build_mailto(["- Milk"], "Shopping list")

    assert link.startswith("mailto:?subject=")
    assert opened(link)[0] == ""


def test_a_long_list_is_cut_to_fit_and_says_how_many_were_left_off():
    entries = list_entries([(f"ingredient number {n}", "1 1/2 cups") for n in range(200)])

    link, included = build_mailto(entries, "Shopping list, Sep 28 - Oct 3", "me@example.com")

    assert len(link) <= MAILTO_LIMIT
    assert 0 < included < 200
    body = opened(link)[2]
    assert body.endswith(f"...and {200 - included} more (see the kiosk)")
    assert body.count("- Ingredient") == included  # the first ones, in order, none skipped
    assert "- Ingredient number 0:" in body


def test_a_list_that_fits_is_not_cut_and_has_no_left_off_note():
    link, included = build_mailto(list_entries([("milk", "1 cup")] * 10), "Shopping list")

    assert included == 10
    assert "more (see the kiosk)" not in opened(link)[2]


def test_the_biggest_message_still_makes_a_code_a_phone_can_read():
    entries = list_entries([(f"ingredient number {n}", "1 1/2 cups") for n in range(500)])

    link, _ = build_mailto(entries, "Shopping list, Sep 28 - Oct 3", "someone.with.a.long.address@example.com")
    code = segno.make(link, error="l", micro=False)

    assert code.version <= 31  # 141 modules across: dense, which is why the kiosk shows it large


# --- salt and pepper -----------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["salt", "Salt", "pepper", "salt pepper", "Salt & Pepper", "kosher salt", "sea salt", "black pepper", "white pepper",
     "freshly ground black pepper", "coarse kosher salt"],
)  # fmt: skip
def test_salt_and_pepper_are_staples_however_a_recipe_words_them(name):
    assert is_staple(name)


@pytest.mark.parametrize(
    "name",
    ["bell peppers", "red pepper flakes", "cayenne pepper", "pepper jack cheese", "peppercorns", "salted butter", "salt cod", "peanut butter", "garlic salt"],
)  # fmt: skip
def test_anything_else_with_pepper_or_salt_in_its_name_is_not(name):
    assert not is_staple(name)
