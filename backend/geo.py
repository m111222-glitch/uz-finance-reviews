"""Infer a review's country from its text when the store doesn't say.

Google Play exposes no reviewer country (not in the public listing, the Developer
API or the review exports). The one reliable signal is reviewers saying where
they are, mostly migrants in Russia reporting the app fails there. Language is
not a signal: Tajik and Uzbek speakers in Russia write in their own languages.
"""

from __future__ import annotations

import re

# "in / from Russia", Moscow, a Russian IP — in Russian, Uzbek and Tajik. Not
# "to Russia" (россию), "Russian card" (российск…), Uzbek "from Russia" (-dan),
# or "came back from Russia", which describe money or trips, not location.
RUSSIA = re.compile(
    r"(?:\bв|\bна|\bдар|(?<!приехал )(?<!приехали )(?<!вернулся )\bиз)\s+(?:росси(?!йск|ю)|рф\b)"
    r"|терр\w*\s+росс|росси[яи]\s?да\b|рассие|\bросия\b|москв(?!у)"
    r"|rossiya(?:da(?!n)|\b)|russia(?:da(?!n)|\b)|русск\w* ip|российск\w* ip",
    re.I,
)
# Only count it when the review is about using the app there
USING_IT_THERE = re.compile(
    r"не работа|не груз|не загруж|не заход|не открыв|неоткри|не получа|не могу|не возможно|невозможно"
    r"|перестал|нахож|нахжусь|впн|vpn|\bip\b|кор намекунад|ishlama|ишлама|буксует|белый экран"
    r"|только грузится|hozir",
    re.I,
)
TRANSFER_FROM_RUSSIA = re.compile(
    r"(?:перевод\w*|отправить)\s+(?:\S+\s+){0,4}из\s+(?:росси|рф)"
    r"|из\s+(?:росси|рф)\w*\s+(?:\S+\s+){0,2}(?:отправ|перев)",
    re.I,
)


def infer_country(text: str | None) -> str | None:
    if text and RUSSIA.search(text) and USING_IT_THERE.search(text) and not TRANSFER_FROM_RUSSIA.search(text):
        return "ru"
    return None
