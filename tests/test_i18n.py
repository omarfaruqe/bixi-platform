"""Guards that keep the English and French interfaces in sync."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from bixi.app.registry import PAGES
from bixi.i18n import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    MissingTranslationError,
    Translator,
    load_catalog,
    normalize_language,
)

PLACEHOLDER = re.compile(r"\{(\w+)\}")
SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def _plain(text: str) -> str:
    """Replace non-breaking spaces so assertions are readable."""
    return text.replace("\u00a0", " ").replace("\u202f", " ")


def test_catalogs_have_identical_keys():
    en, fr = set(load_catalog("en")), set(load_catalog("fr"))
    assert en == fr, f"only in en: {sorted(en - fr)}; only in fr: {sorted(fr - en)}"


def test_no_empty_messages():
    for language in SUPPORTED_LANGUAGES:
        empty = [key for key, text in load_catalog(language).items() if not text.strip()]
        assert not empty, f"{language}: empty messages {empty}"


def test_placeholders_match_across_languages():
    en, fr = load_catalog("en"), load_catalog("fr")
    for key in en:
        assert set(PLACEHOLDER.findall(en[key])) == set(PLACEHOLDER.findall(fr[key])), key


def test_every_page_has_translations():
    catalog = load_catalog(DEFAULT_LANGUAGE)
    for spec in PAGES:
        assert f"nav.{spec.key}" in catalog
        assert f"pages.{spec.key}.description" in catalog


def test_translation_keys_used_in_code_exist():
    """Every literal t("...") call in the source must exist in the catalogs."""
    pattern = re.compile(r"""\bt\(\s*f?["']([a-z0-9_.]+)["']""")
    catalog = load_catalog(DEFAULT_LANGUAGE)
    missing = []
    for path in SRC_DIR.rglob("*.py"):
        for key in pattern.findall(path.read_text(encoding="utf-8")):
            if key not in catalog:
                missing.append(f"{path.name}: {key}")
    assert not missing, missing


def test_navigation_labels_match_spec():
    en, fr = Translator("en"), Translator("fr")
    assert en.t("nav.station_map") == "Station map"
    assert fr.t("nav.station_map") == "Carte des stations"
    assert fr.t("nav.methodology") == "Données et méthodologie"


def test_placeholder_substitution():
    assert "x.parquet" in Translator("fr").t("errors.data_not_found", path="x.parquet")


def test_unknown_key_falls_back_to_key_or_raises_in_strict_mode():
    assert Translator("fr").t("does.not.exist") == "does.not.exist"
    try:
        Translator("fr", strict=True).t("does.not.exist")
    except MissingTranslationError:
        pass
    else:
        raise AssertionError("strict mode should raise")


def test_language_normalisation():
    assert normalize_language("FR") == "fr"
    assert normalize_language("fr-CA") == "fr"
    assert normalize_language("de") == DEFAULT_LANGUAGE
    assert normalize_language(None) == DEFAULT_LANGUAGE


def test_number_formatting_follows_language():
    assert _plain(Translator("en").number(1234567.891, decimals=1)) == "1,234,567.9"
    assert _plain(Translator("fr").number(1234567.891, decimals=1)) == "1 234 567,9"


def test_percent_formatting_follows_language():
    assert _plain(Translator("en").percent(0.125)) == "12.5%"
    assert _plain(Translator("fr").percent(0.125)) == "12,5 %"


def test_date_formatting_follows_language():
    day = date(2025, 7, 14)
    assert Translator("en").date(day) == "July 14, 2025"
    assert Translator("fr").date(day) == "14 juillet 2025"


def test_weekday_and_month_names_follow_language():
    assert Translator("en").weekday_names()[0] == "Mon"
    assert Translator("fr").weekday_names()[0].startswith("lun")
    assert Translator("en").month_names()[7] == "Jul"
    assert Translator("fr").month_names()[7].startswith("juil")


def test_hour_labels_follow_language():
    assert Translator("en").hour(8) == "08:00"
    assert Translator("fr").hour(8) == "8 h"
