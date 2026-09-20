"""One-time setup for the voice assistant: `python -m app.voice.setup`.

Downloads the speech-recognition model into data/voice/models. This is the one
step that fetches a large file, so it is a deliberate command you run (and can
see the size of) rather than something the app does on its own.
"""

import argparse
import sys

from ..config import settings
from .stt import WhisperTranscriber, installed_model_files


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Install the local speech-recognition model.")
    parser.add_argument("--model", default=settings.voice_stt_model, help="faster-whisper model name (default: %(default)s)")
    parser.add_argument("--check", action="store_true", help="report what is installed; download nothing")
    args = parser.parse_args(argv)

    present = installed_model_files(args.model)
    if args.check or present:
        ready, detail = WhisperTranscriber().status()
        print(f"model {args.model!r}: {'installed' if present else 'not installed'}; recognizer: {detail}")
        return 0 if present else 1

    try:
        from faster_whisper.utils import download_model
    except ImportError:
        print("faster-whisper isn't installed: pip install -r requirements.txt", file=sys.stderr)
        return 2

    settings.voice_models_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading speech model {args.model!r} from Hugging Face into {settings.voice_models_dir} ...")
    path = download_model(args.model, cache_dir=str(settings.voice_models_dir))
    print(f"Done: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
