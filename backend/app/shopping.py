"""Turning the week's recipes into one shopping list.

Each recipe stores its ingredients as {raw_text, name, quantity_text} (see
recipes/ingredient_parsing.py): "1 1/2 lb chicken breast" is name "chicken
breast" with quantity "1 1/2 lb". Here the same ingredient from different
recipes is put on one line and its amounts added up where that's safe:

    "1 1/2 lb" + "1 lb"     -> "2 1/2 lb"
    "1 cup"    + "2 tbsp"   -> "1 cup + 2 tbsp"   (different units aren't converted)
    "1 1/2-2 cups" + "1 cup" -> "1 1/2-2 cups + 1 cup"   (a range is left as written)

Best effort, like the parsing under it: when in doubt it keeps both amounts
rather than guessing, so the list can be a little long but is never wrong.
"""

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

# A leading amount: "1 1/2", "3/4", "2", "0.5". What follows is the unit.
_AMOUNT = re.compile(r"^\s*(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*(.*?)\s*$")

# Ways of writing the common units, folded into one. Anything else is a unit
# of its own ("clove", "packet"), singularized so "2 cans" and "1 can" meet.
_UNITS = {
    "tbsp": "tbsp", "tbsps": "tbsp", "tbs": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "tsp": "tsp", "tsps": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "cup": "cup", "cups": "cup", "c": "cup",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "g": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml",
    "l": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "qt": "qt", "quart": "qt", "quarts": "qt",
    "pt": "pt", "pint": "pt", "pints": "pt",
    "gal": "gal", "gallon": "gal", "gallons": "gal",
}
# Units that read the same singular and plural ("2 tbsp", "3 lb").
_NEVER_PLURAL = {"tbsp", "tsp", "lb", "oz", "g", "kg", "ml", "l", "qt", "pt", "gal"}


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "xes", "sses", "oes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us")) and len(word) > 3:
        return word[:-1]
    return word


def _plural(unit: str) -> str:
    if unit.endswith(("ch", "sh", "x", "s")):
        return unit + "es"
    return unit + "s"


def normalize_name(name: str) -> str:
    """What two lines must share to be the same thing to buy: "Carrots" and
    "carrot" do, "carrots" and "baby carrots" don't."""
    words = re.sub(r"[^\w\s]", " ", name.lower()).split()
    if words:
        words[-1] = _singular(words[-1])
    return " ".join(words)


def parse_quantity(text: Optional[str]) -> Tuple[Optional[Fraction], str]:
    """("1 1/2 lb") -> (Fraction(3, 2), "lb"); ("2") -> (Fraction(2), ""). An amount
    that can't be added up ("a handful", "1 1/2-2 cups") gives (None, "")."""
    if not text or not text.strip():
        return None, ""
    match = _AMOUNT.match(text)
    if not match:
        return None, ""
    number, rest = match.groups()
    if rest[:1] in ("-", "–", "—") or rest[:1].isdigit() or rest.lower().startswith("to "):
        return None, ""  # "1 1/2-2 cups", "2 to 3": a range
    parts = number.split()
    amount = sum((Fraction(part) for part in parts), Fraction(0))
    unit = re.sub(r"[.,;]+$", "", rest.strip().lower())
    if unit and not re.fullmatch(r"[a-z]+(?: [a-z]+)*", unit):
        return None, ""  # "cans (15 oz)": a size note in the unit; different sizes shouldn't be added up
    return amount, _UNITS.get(unit) or _singular(unit)


def format_amount(amount: Fraction) -> str:
    """Fraction(5, 2) -> "2 1/2"."""
    amount = amount.limit_denominator(16)
    whole, remainder = divmod(amount.numerator, amount.denominator)
    if remainder == 0:
        return str(whole)
    fraction = f"{remainder}/{amount.denominator}"
    return f"{whole} {fraction}" if whole else fraction


def _format(amount: Fraction, unit: str) -> str:
    if not unit:
        return format_amount(amount)
    shown = unit if unit in _NEVER_PLURAL or amount <= 1 else _plural(unit)
    return f"{format_amount(amount)} {shown}"


@dataclass
class _Line:
    name: str  # as first written
    amounts: Dict[str, Fraction] = field(default_factory=dict)  # unit -> total
    unsummable: List[str] = field(default_factory=list)  # amounts left as written
    recipes: List[str] = field(default_factory=list)

    def quantity(self) -> str:
        pieces = [_format(amount, unit) for unit, amount in self.amounts.items()]
        return " + ".join(pieces + self.unsummable)


@dataclass
class ShoppingLine:
    key: str
    name: str
    quantity: str
    recipes: List[str]


def build_lines(meals: Iterable[Tuple[str, Sequence[Dict[str, Any]]]]) -> List[ShoppingLine]:
    """One line per ingredient across (recipe title, ingredients) for each planned
    meal, in alphabetical order. A recipe planned twice counts twice."""
    lines: Dict[str, _Line] = {}
    for title, ingredients in meals:
        for ingredient in ingredients or []:
            name = (ingredient.get("name") or ingredient.get("raw_text") or "").strip()
            key = normalize_name(name)
            if not key:
                continue
            line = lines.setdefault(key, _Line(name=name))
            if title not in line.recipes:
                line.recipes.append(title)

            quantity_text = ingredient.get("quantity_text")
            amount, unit = parse_quantity(quantity_text)
            if amount is not None:
                line.amounts[unit] = line.amounts.get(unit, Fraction(0)) + amount
            elif quantity_text and quantity_text.strip():
                line.unsummable.append(quantity_text.strip())

    return [
        ShoppingLine(key=key, name=line.name, quantity=line.quantity(), recipes=line.recipes)
        for key, line in sorted(lines.items())
    ]


# --- sending the list to a phone ------------------------------------------------
#
# The kiosk shows a QR code; scanning it with a phone's camera opens a new email with
# the list already in it (a mailto: link, so nothing needs setting up and nothing is
# sent from the kiosk). A QR code can only hold so much before it gets too dense for a
# phone to read across a kitchen, so a long list is cut short and says so.

MAILTO_LIMIT = 1800  # bytes of link: a code 141 modules across at most, so the kiosk draws it large


def list_entries(items: Iterable[Tuple[str, str]]) -> List[str]:
    """[("chicken breast", "1 1/2 lb"), ("paper towels", "")] -> ["- Chicken breast: 1 1/2 lb", "- Paper towels"]"""
    entries = []
    for name, quantity in items:
        label = name[:1].upper() + name[1:]
        entries.append(f"- {label}: {quantity}" if quantity else f"- {label}")
    return entries


def build_mailto(entries: Sequence[str], header: str, to: str = "", limit: int = MAILTO_LIMIT) -> Tuple[str, int]:
    """(link, how many entries fit). Drops entries from the end until the link fits, and
    says how many were left off, so the message never silently loses items."""
    subject = quote("Shopping list", safe="")
    recipient = quote(to.strip(), safe="@,+")
    for included in range(len(entries), -1, -1):
        lines = [header, ""] + list(entries[:included])
        if included < len(entries):
            lines.append(f"...and {len(entries) - included} more (see the kiosk)")
        link = f"mailto:{recipient}?subject={subject}&body={quote(chr(10).join(lines), safe='')}"
        if len(link) <= limit:
            return link, included
    return link, 0
