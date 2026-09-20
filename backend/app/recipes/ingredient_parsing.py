import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


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
        name = " ".join(part.text for part in parsed.name) if parsed.name else raw_text
        quantity_text = parsed.amount[0].text if parsed.amount else None
        return {"raw_text": raw_text, "name": name, "quantity_text": quantity_text}
    except Exception:
        logger.exception("Ingredient parsing failed for %r — storing unparsed", raw_text)
        return {"raw_text": raw_text, "name": raw_text, "quantity_text": None}
