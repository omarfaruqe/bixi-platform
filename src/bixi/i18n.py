"""Lightweight internationalisation: JSON catalogs plus locale-aware formatting.

Design rules
------------
* English is the default and the fallback language.
* Message keys are dotted paths into the JSON catalogs (``nav.overview``).
* Placeholders use ``str.format`` syntax (``{path}``) and must match across languages;
  the test suite enforces this.
* Numbers and dates are formatted with Babel using Canadian locales (en_CA / fr_CA),
  because the data is about Montréal. Station names are never translated.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

from babel import Locale
from babel.dates import format_date, format_datetime, get_day_names, get_month_names
from babel.numbers import format_decimal, format_percent

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "fr")
DEFAULT_LANGUAGE = "en"
LANGUAGE_NAMES: Mapping[str, str] = MappingProxyType({"en": "English", "fr": "Français"})

LOCALES_DIR = Path(__file__).parent / "locales"
_BABEL_LOCALES = {"en": "en_CA", "fr": "fr_CA"}


class MissingTranslationError(KeyError):
    """Raised in strict mode when a key is missing from every catalog."""


def normalize_language(value: object) -> str:
    """Map user input such as 'FR', 'fr-CA' or None to a supported language code."""
    if not value:
        return DEFAULT_LANGUAGE
    code = str(value).strip().lower().replace("_", "-").split("-")[0]
    return code if code in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def _flatten(data: Mapping[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in data.items():
        full_key = f"{prefix}{key}"
        if isinstance(value, Mapping):
            flat.update(_flatten(value, f"{full_key}."))
        else:
            flat[full_key] = value
    return flat


@cache
def load_catalog(language: str) -> Mapping[str, str]:
    """Load one language catalog as a flat, read-only ``{dotted.key: message}`` mapping."""
    path = LOCALES_DIR / f"{language}.json"
    with path.open(encoding="utf-8") as handle:
        return MappingProxyType(_flatten(json.load(handle)))


@dataclass(frozen=True)
class Translator:
    """Translate messages and format numbers/dates for one language."""

    language: str = DEFAULT_LANGUAGE
    strict: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", normalize_language(self.language))

    @property
    def locale(self) -> str:
        return _BABEL_LOCALES[self.language]

    def t(self, key: str, **params: object) -> str:
        """Translate ``key``; fall back to English, then to the key itself (or raise if strict)."""
        message = load_catalog(self.language).get(key)
        if message is None:
            message = load_catalog(DEFAULT_LANGUAGE).get(key)
        if message is None:
            if self.strict:
                raise MissingTranslationError(key)
            return key
        return message.format(**params) if params else message

    def number(self, value: float, decimals: int = 0) -> str:
        pattern = "#,##0" + (f".{'0' * decimals}" if decimals else "")
        return format_decimal(value, format=pattern, locale=self.locale)

    def percent(self, value: float, decimals: int = 1) -> str:
        """Format a fraction (0.125) as a percentage ('12.5%' / '12,5 %')."""
        # Reuse the locale's own pattern so spacing is right ("12.5%" vs "12,5 %").
        base = Locale.parse(self.locale).percent_formats[None].pattern
        digits = "#,##0" + (f".{'0' * decimals}" if decimals else "")
        pattern = re.sub(r"#,##0(\.0+)?", digits, base, count=1)
        return format_percent(value, format=pattern, locale=self.locale)

    def date(self, value: date, style: str = "long") -> str:
        return format_date(value, format=style, locale=self.locale)

    def datetime(self, value: datetime, style: str = "medium") -> str:
        return format_datetime(value, format=style, locale=self.locale)

    def weekday_names(self, width: str = "abbreviated") -> list[str]:
        """Monday-first weekday names ('Mon' / 'lun.')."""
        names = get_day_names(width, context="format", locale=self.locale)
        return [names[i] for i in range(7)]

    def month_names(self, width: str = "abbreviated") -> dict[int, str]:
        """Month names keyed 1-12 ('Jul' / 'juil.')."""
        return dict(get_month_names(width, context="stand-alone", locale=self.locale))

    def hour(self, value: int) -> str:
        """Clock hour label: '17:00' in English, '17 h' in French (Québec usage)."""
        return f"{value} h" if self.language == "fr" else f"{value:02d}:00"
