"""A Claude-API fallback for open-ended questions the rule-based commands
above can't answer ("what's a good substitute for buttermilk?").

Off by default, and deliberately the one place anything voice-related leaves
the house: speech recognition and every other command are local (see
app/voice/stt.py), but there is no local answer to a genuinely open question,
so its *text* — never audio — goes to Anthropic's Messages API instead, and
only once both HOME_ORGANIZER_VOICE_CLAUDE_ENABLED and an API key are set.
See deploy/README.md "Voice assistant" for how to turn it on.

Shaped like the other skills (a plain function of (text, Context)) so it
slots into router.SKILLS as the last one tried, rather than needing its own
wiring in route(): every other skill declines by returning None when a
command isn't its kind of thing; this one "declines" the same way when it
isn't turned on, so with it off, route() behaves exactly as before.
"""

import logging
from typing import Optional

from ...config import settings
from ..core import Context, Reply
from ..text import spoken_clock

logger = logging.getLogger(__name__)

# A couple of spoken sentences' worth — this is a kiosk reply, not a chat transcript.
MAX_TOKENS = 200

SYSTEM_PROMPT = (
    "You are the voice assistant on a household kiosk, answering a question a rule-based "
    "system could not handle itself. Reply in one or two short, plain sentences meant to be "
    "read aloud: no lists, no markdown, no asterisks. If you don't know, say so briefly "
    "rather than guessing at length."
)

UNAVAILABLE = "Sorry, I couldn't reach Claude just now."


def available() -> bool:
    return bool(settings.voice_claude_enabled and settings.voice_claude_api_key)


def _context_line(ctx: Context) -> str:
    """A little grounding — today's date/time, and what the kiosk already
    knows about weather and location — so answers like "what should I wear
    today" don't require a second round trip just to ask."""
    local = ctx.now_local
    parts = [f"Today is {local.strftime('%A, %B')} {local.day}, {local.year}, {spoken_clock(local.hour, local.minute)}."]
    if ctx.location_name:
        parts.append(f"The household is near {ctx.location_name}.")
    current = (ctx.weather or {}).get("current")
    if current:
        unit = "F" if "F" in (ctx.weather.get("unit") or "") else "C"
        parts.append(f"Current weather: {current.get('description', '')}, {round(current.get('temperature', 0))}°{unit}.")
    return " ".join(parts)


def _call_claude(system: str, text: str) -> str:
    """The one network call, isolated so tests can replace it without
    reaching into the anthropic package or a real API key."""
    import anthropic

    client = anthropic.Anthropic(api_key=settings.voice_claude_api_key, timeout=settings.voice_claude_timeout_seconds)
    response = client.messages.create(
        model=settings.voice_claude_model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": text}],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()


def handle(text: str, ctx: Context) -> Optional[Reply]:
    if not available():
        return None
    try:
        answer = _call_claude(f"{SYSTEM_PROMPT} {_context_line(ctx)}", text).strip()
    except Exception:
        logger.exception("Claude fallback failed")
        return Reply(UNAVAILABLE, understood=False)
    if not answer:
        return Reply(UNAVAILABLE, understood=False)
    return Reply(answer)
