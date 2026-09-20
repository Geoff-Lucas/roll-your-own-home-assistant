import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _clean_name(name: str) -> str:
    """Drop stray symbols the NLP model leaves in names, e.g. the '~' from
    "taco seasoning (~2 Tbsp.)" becoming "taco seasoning ~"."""
    tokens = [token for token in name.split() if re.search(r"\w", token)]
    return re.sub(r"^\W+|\W+$", "", " ".join(tokens))


def _unit_as_written(amount_text: str, raw_text: str) -> str:
    """The library normalizes units (pluralizes by quantity, expands or
    abbreviates them): "3/4 cup" comes back as "3/4 cups" and "1 1/2 - 2
    cups" as "1 1/2-2 cup". The original line is the source of truth, so put
    the unit back the way the recipe wrote it."""
    quantity, _, unit = amount_text.rpartition(" ")
    if not quantity or not unit:
        return amount_text
    variants = {unit, unit + "s"}
    if unit.endswith("s"):
        variants.add(unit[:-1])
    pattern = r"\b(?:" + "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True)) + r")\b"
    written = re.search(pattern, raw_text, flags=re.IGNORECASE)
    return f"{quantity} {written.group(0)}" if written else amount_text


def parse_ingredient_line(raw_text: str) -> Dict[str, Any]:
    """Best-effort structuring of one ingredient line.

    raw_text is always preserved verbatim as the source of truth; name and
    quantity_text are derived for a future shopping-list feature to group
    by. Uses `ingredient-parser-nlp` (see PLAN.md Recipes section for why —
    Grocy, the other reference point, turns out to require fully manual
    entry with nothing to borrow). Any failure here — including the
    library's one-time NLTK model download not being available — falls back
    to the unparsed shape rather than blocking the recipe from saving.
    """
    try:
        from ingredient_parser import parse_ingredient

        parsed = parse_ingredient(raw_text)

        # A "label: a, b, c" line with no quantity (e.g. "optional add-ins:
        # guacamole, avocado") is a note, not an ingredient — the model would
        # otherwise pick one arbitrary item from it as the name.
        if not parsed.amount and ":" in raw_text:
            return {"raw_text": raw_text, "name": raw_text, "quantity_text": None}

        name = _clean_name(" ".join(part.text for part in parsed.name)) if parsed.name else ""
        quantity_text = _unit_as_written(parsed.amount[0].text, raw_text) if parsed.amount else None
        return {"raw_text": raw_text, "name": name or raw_text, "quantity_text": quantity_text}
    except Exception:
        logger.exception("Ingredient parsing failed for %r — storing unparsed", raw_text)
        return {"raw_text": raw_text, "name": raw_text, "quantity_text": None}
