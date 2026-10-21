"""Command line interface:  python -m bixi.download {trips,stations,weather,all}"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from bixi.config import get_settings
from bixi.download.http import DownloadError
from bixi.download.stations import download_gbfs
from bixi.download.trips import TRIP_ARCHIVES, download_trips
from bixi.download.weather import download_weather

DEFAULT_YEARS = (2023, 2024, 2025)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m bixi.download", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser, *, years: bool = True) -> None:
        if years:
            p.add_argument(
                "--years",
                nargs="+",
                type=int,
                default=list(DEFAULT_YEARS),
                help=f"default: {' '.join(map(str, DEFAULT_YEARS))}; "
                f"trips available for: {' '.join(map(str, sorted(TRIP_ARCHIVES)))}",
            )
        p.add_argument("--force", action="store_true", help="download again even if present")

    trips = sub.add_parser("trips", help="BIXI trip history ZIPs, extracted to CSV")
    add_common(trips)
    trips.add_argument(
        "--skip-download",
        action="store_true",
        help="only extract ZIPs already placed in data/raw/trips/zips/",
    )
    stations = sub.add_parser("stations", help="current station list and capacities (GBFS)")
    add_common(stations, years=False)
    add_common(sub.add_parser("weather", help="hourly weather from Open-Meteo"))
    everything = sub.add_parser("all", help="trips + stations + weather")
    add_common(everything)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    raw_dir = get_settings().raw_dir
    command = args.command

    try:
        if command in ("trips", "all"):
            download_trips(
                args.years,
                raw_dir,
                force=args.force,
                skip_download=getattr(args, "skip_download", False),
            )
        if command in ("stations", "all"):
            download_gbfs(raw_dir)
        if command in ("weather", "all"):
            download_weather(args.years, raw_dir, force=args.force)
    except (DownloadError, FileNotFoundError, ValueError) as error:
        logging.error("%s", error)
        logging.error(
            "If a BIXI link no longer works, download the ZIPs from "
            "https://bixi.com/en/open-data/ into data/raw/trips/zips/ and run: "
            "python -m bixi.download trips --skip-download"
        )
        return 1

    logging.info("Done. Raw data is under %s", raw_dir)
    return 0
