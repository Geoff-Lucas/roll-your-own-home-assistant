from app import config
from app.ambient.photos import list_photo_filenames


def test_returns_empty_list_when_directory_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)  # ambient_photos_dir derives from this, never created
    assert list_photo_filenames() == []


def test_lists_only_image_files_sorted(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    photos_dir = config.settings.ambient_photos_dir
    photos_dir.mkdir(parents=True)
    (photos_dir / "b.jpg").write_bytes(b"fake")
    (photos_dir / "a.png").write_bytes(b"fake")
    (photos_dir / "notes.txt").write_bytes(b"not an image")
    (photos_dir / "sub").mkdir()

    assert list_photo_filenames() == ["a.png", "b.jpg"]
