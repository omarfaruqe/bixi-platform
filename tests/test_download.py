"""Download-package tests. They never touch the network (file:// URLs and local ZIPs only)."""

from __future__ import annotations

import json
import zipfile
from datetime import date

from bixi.download import manifest
from bixi.download.http import DownloadError, download_file
from bixi.download.stations import extract_feed_urls
from bixi.download.trips import TRIP_ARCHIVES, archive_url, download_trips, extract_csvs
from bixi.download.weather import ARCHIVE_LAG_DAYS, request_params


def test_default_scope_years_have_official_archives():
    for year in (2023, 2024, 2025):
        assert archive_url(year).startswith("https://cdn.bixi.com/")
    assert set(TRIP_ARCHIVES) >= {2023, 2024, 2025}


def test_unknown_year_is_rejected_with_available_years():
    try:
        archive_url(1999)
    except ValueError as error:
        assert "2023" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_download_file_writes_atomically_and_checksums(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"hello bixi")
    dest = tmp_path / "out" / "copy.bin"
    info = download_file(source.as_uri(), dest)
    assert dest.read_bytes() == b"hello bixi"
    assert info.size_bytes == 10
    assert len(info.sha256) == 64
    assert not (tmp_path / "out" / "copy.bin.part").exists()


def test_failed_download_leaves_no_partial_file(tmp_path):
    dest = tmp_path / "missing.bin"
    try:
        download_file((tmp_path / "does_not_exist").as_uri(), dest, retries=1, backoff=0)
    except DownloadError:
        pass
    else:
        raise AssertionError("expected DownloadError")
    assert not dest.exists()
    assert not (tmp_path / "missing.bin.part").exists()


def _make_zip(path, members: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)


def test_extract_csvs_keeps_only_csv_and_skips_junk(tmp_path):
    zip_path = tmp_path / "a.zip"
    _make_zip(
        zip_path,
        {
            "2025/04.csv": b"a,b\n1,2\n",
            "readme.txt": b"ignore me",
            "__MACOSX/2025/._04.csv": b"junk",
            "2025/._05.csv": b"junk",
        },
    )
    files = extract_csvs(zip_path, tmp_path / "out")
    assert [f.name for f in files] == ["04.csv"]


def test_extract_csvs_rejects_path_traversal(tmp_path):
    zip_path = tmp_path / "evil.zip"
    _make_zip(zip_path, {"../escape.csv": b"x"})
    try:
        extract_csvs(zip_path, tmp_path / "out")
    except DownloadError:
        pass
    else:
        raise AssertionError("expected DownloadError")
    assert not (tmp_path / "escape.csv").exists()


def test_download_trips_skip_download_extracts_local_zip(tmp_path):
    zip_path = tmp_path / "trips" / "zips" / archive_url(2023).rsplit("/", 1)[-1]
    zip_path.parent.mkdir(parents=True)
    _make_zip(zip_path, {"2023_04.csv": b"a,b\n1,2\n"})
    results = download_trips([2023], tmp_path, skip_download=True)
    assert [f.name for f in results[2023]] == ["2023_04.csv"]


def test_download_trips_skip_download_without_zip_explains_what_to_do(tmp_path):
    try:
        download_trips([2024], tmp_path, skip_download=True)
    except FileNotFoundError as error:
        assert "bixi.com" in str(error)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_gbfs_feed_urls_v2_per_language_and_v3_flat():
    v2 = {
        "data": {
            "en": {
                "feeds": [
                    {"name": "station_information", "url": "u1"},
                    {"name": "vehicle_types", "url": "ignored"},
                ]
            }
        }
    }
    v3 = {"data": {"feeds": [{"name": "station_status", "url": "u2"}]}}
    assert extract_feed_urls(v2) == {"station_information": "u1"}
    assert extract_feed_urls(v3) == {"station_status": "u2"}
    assert extract_feed_urls({}) == {}


def test_weather_params_full_past_year():
    params = request_params(2024, today=date(2026, 10, 11))
    assert params["start_date"] == "2024-01-01"
    assert params["end_date"] == "2024-12-31"
    assert params["timezone"] == "UTC"


def test_weather_params_cap_current_year_at_archive_lag():
    today = date(2026, 10, 11)
    params = request_params(2026, today)
    assert params["end_date"] == date(2026, 10, 4).isoformat()
    assert ARCHIVE_LAG_DAYS == 7


def test_weather_params_none_when_archive_has_nothing_yet():
    assert request_params(2026, today=date(2026, 1, 3)) is None


def test_manifest_merges_entries(tmp_path):
    manifest.record(tmp_path, "a", url="u1")
    manifest.record(tmp_path, "b", url="u2")
    data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert set(data) == {"a", "b"}
    assert "retrieved_at_utc" in data["a"]
