"""One-time setup for the voice assistant: `python -m app.voice.setup`.

Downloads the speech-recognition model into data/voice/models, or with
`--piper NAME` a Piper reply voice into data/voice/piper. These are the steps
that fetch large files, so they are deliberate commands you run (and can see
the size of) rather than something the app does on its own.
"""

import argparse
import subprocess
import sys

from ..config import settings
from .stt import WhisperTranscriber, installed_model_files


def install_piper_voice(name: str) -> int:
    """Fetch a Piper voice (about 60 MB for a medium one) from Hugging Face."""
    target = settings.voice_piper_dir
    if (target / f"{name}.onnx").exists():
        print(f"Piper voice {name!r} is already installed in {target}")
        return 0
    target.mkdir(parents=True, exist_ok=True)
    print(f"Downloading Piper voice {name!r} from Hugging Face (rhasspy/piper-voices) into {target} ...")
    code = subprocess.run([sys.executable, "-m", "piper.download_voices", name, "--data-dir", str(target)]).returncode
    if code == 0:
        print(f"Done. Use it with HOME_ORGANIZER_VOICE_PIPER_MODEL={name}")
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Install the local speech-recognition model or a reply voice.")
    parser.add_argument("--model", default=settings.voice_stt_model, help="faster-whisper model name (default: %(default)s)")
    parser.add_argument("--piper", metavar="VOICE", help="install a Piper voice instead, e.g. en_US-lessac-medium")
    parser.add_argument("--check", action="store_true", help="report what is installed; download nothing")
    args = parser.parse_args(argv)

    if args.piper:
        return install_piper_voice(args.piper)

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
