import shutil

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..voice.session import VoiceBusy, voice
from ..voice.skills.claude_fallback import available as claude_available
from ..voice.tts import choose_speaker

router = APIRouter(prefix="/voice", tags=["voice"])


class TextCommand(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    speak: bool = True


@router.get("/status")
def status() -> dict:
    """What works on this machine — so the UI can say *why* voice isn't ready
    instead of just failing."""
    ready, detail = voice.transcriber.status()
    speaker = choose_speaker()
    return {
        "microphone": shutil.which("arecord") is not None,
        "speech_recognition": {"ready": ready, "detail": detail},
        "speaker": speaker.name if speaker else None,
        "wake_word": voice.wake_status(),
        "ring_commands": settings.voice_ring_listen and ready,
        "claude_fallback": claude_available(),
    }


@router.get("/state")
def state() -> dict:
    return voice.snapshot()


@router.get("/history")
def history() -> list[dict]:
    """The last few interactions, newest first: what was heard, what was
    answered, and how long recognition took. Kept in memory only."""
    return list(reversed(voice.history))


@router.post("/start", status_code=202)
async def start() -> dict:
    try:
        await voice.start()
    except VoiceBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return voice.snapshot()


@router.post("/stop", status_code=204)
def stop() -> None:
    voice.stop()


@router.post("/text")
async def text_command(payload: TextCommand) -> dict:
    """Run a command as if it had been spoken (skips the microphone and speech
    recognition). Useful for typed commands and for checking everything after them."""
    try:
        reply = await voice.say_text(payload.text, speak=payload.speak)
    except VoiceBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"reply": reply.text, "understood": reply.understood}
