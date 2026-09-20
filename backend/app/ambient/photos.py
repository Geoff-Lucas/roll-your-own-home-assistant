from typing import List

from ..config import settings

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def list_photo_filenames() -> List[str]:
    """Filenames (not paths) of images in the ambient photos directory.

    That directory is populated externally (NAS rsync, a Google Photos
    downloader script, etc. — see PLAN.md "Ambient mode") — this only ever
    reads, never fetches or writes photos itself. Sorted for a stable
    carousel order across requests.
    """
    if not settings.ambient_photos_dir.is_dir():
        return []
    return sorted(
        p.name for p in settings.ambient_photos_dir.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS
    )
