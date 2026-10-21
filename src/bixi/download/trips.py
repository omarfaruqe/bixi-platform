"""BIXI trip history: one ZIP per year from BIXI's official open-data page.

Source page:  https://bixi.com/en/open-data/
Licence:      Creative Commons Attribution. Attribute BIXI Montréal in anything you publish.

The archive URLs below were copied from that page. If BIXI reorganises its site and a link
breaks, this dictionary is the only place to update. As a fallback, download the ZIP by hand
into ``data/raw/trips/zips/`` and run ``python -m bixi.download trips --skip-download``.
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path, PurePosixPath

from bixi.download import manifest
from bixi.download.http import DownloadError, download_file

LOGGER = logging.getLogger(__name__)

SOURCE_PAGE = "https://bixi.com/en/open-data/"
LICENSE_NOTE = "Creative Commons Attribution; attribute BIXI Montréal"

TRIP_ARCHIVES: dict[int, str] = {
    2023: "https://cdn.bixi.com/wp-content/uploads/2024/01/DonneesOuvertes2023_12.zip",
    2024: "https://cdn.bixi.com/wp-content/uploads/2025/01/DonneesOuvertes2024_010203040506070809101112.zip",  # noqa: E501
    2025: "https://cdn.bixi.com/wp-content/uploads/2026/02/DonneesOuvertes2025_010203040506070809101112.zip",  # noqa: E501
    # Partial year (still being published). Useful later as a genuine out-of-time test set.
    2026: "https://cdn.bixi.com/wp-content/uploads/2026/02/DonneesOuvertes2026_0102030405060708.zip",  # noqa: E501
}


def archive_url(year: int) -> str:
    try:
        return TRIP_ARCHIVES[year]
    except KeyError:
        available = ", ".join(str(y) for y in sorted(TRIP_ARCHIVES))
        raise ValueError(f"No BIXI archive configured for {year}. Available: {available}") from None


def extract_csvs(zip_path: Path, out_dir: Path) -> list[Path]:
    """Extract only the CSV files, ignoring macOS junk and refusing unsafe paths."""
    extracted: list[Path] = []
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = PurePosixPath(info.filename)
            if info.is_dir() or not info.filename.lower().endswith(".csv"):
                continue
            if "__MACOSX" in name.parts or name.name.startswith("._"):
                continue
            if name.is_absolute() or ".." in name.parts:
                raise DownloadError(f"Unsafe path in {zip_path.name}: {info.filename}")
            target = out_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            extracted.append(target)
    return sorted(extracted)


def download_trips(
    years: list[int] | tuple[int, ...],
    raw_dir: Path,
    *,
    force: bool = False,
    skip_download: bool = False,
) -> dict[int, list[Path]]:
    """Download (unless already present) and extract the trip archive for each year."""
    results: dict[int, list[Path]] = {}
    for year in years:
        url = archive_url(year)
        zip_path = raw_dir / "trips" / "zips" / url.rsplit("/", 1)[-1]

        if skip_download:
            if not zip_path.exists():
                raise FileNotFoundError(
                    f"{zip_path} not found. Download it from {SOURCE_PAGE} and place it there."
                )
        elif zip_path.exists() and not force:
            LOGGER.info("%s: %s already downloaded (use --force to refetch)", year, zip_path.name)
        else:
            LOGGER.info("%s: downloading %s", year, url)
            info = download_file(url, zip_path)
            LOGGER.info("%s: %.1f MB, sha256 %s", year, info.size_bytes / 1e6, info.sha256[:12])
            manifest.record(
                raw_dir,
                f"trips_{year}",
                url=url,
                path=str(zip_path),
                bytes=info.size_bytes,
                sha256=info.sha256,
                license=LICENSE_NOTE,
                source_page=SOURCE_PAGE,
            )

        if not zipfile.is_zipfile(zip_path):
            raise DownloadError(
                f"{zip_path} is not a valid ZIP file (the site may have returned an error page). "
                "Delete it and retry, or download it manually."
            )

        files = extract_csvs(zip_path, raw_dir / "trips" / str(year))
        out_dir = raw_dir / "trips" / str(year)
        LOGGER.info("%s: extracted %d CSV file(s) to %s", year, len(files), out_dir)
        results[year] = files
    return results
