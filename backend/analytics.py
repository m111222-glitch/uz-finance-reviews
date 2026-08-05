"""Lightweight review analytics helpers."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

# Common tokens in RU/UZ finance app reviews (stopwords stripped)
STOPWORDS = {
    "и", "в", "на", "не", "что", "это", "с", "по", "для", "как", "из", "а", "то",
    "но", "к", "у", "же", "от", "за", "о", "так", "все", "его", "её", "ее", "мы",
    "вы", "они", "он", "она", "я", "мне", "меня", "был", "была", "были", "быть",
    "есть", "нет", "да", "уже", "еще", "ещё", "только", "можно", "нужно", "очень",
    "когда", "если", "или", "чтобы", "при", "до", "после", "без", "под", "над",
    "the", "a", "an", "and", "or", "to", "of", "in", "is", "it", "for", "on",
    "with", "this", "that", "app", "приложение", "приложения", "приложении",
    "банк", "банка", "банком", "очень", "просто", "всегда", "иногда", "вообще",
    "хорошо", "плохо", "нормально", "спасибо", "пожалуйста", "почему", "какой",
    "какая", "какие", "который", "которая", "которые", "свой", "своя", "свои",
    "ваш", "ваша", "ваши", "мой", "моя", "мои", "там", "тут", "здесь", "теперь",
    "потом", "сейчас", "больше", "меньше", "через", "будет", "было", "будут",
    "va", "va", "ham", "bilan", "uchun", "bu", "shu", "juda", "yaxshi", "yomon",
    "kerak", "mumkin", "emas", "bor", "yoq", "yo'q", "qilib", "qiladi", "qilish",
}

THEME_PATTERNS: dict[str, list[str]] = {
    "payments": [
        r"плат[её]ж", r"перевод", r"p2p", r"оплат", r"комисс", r"to'lov", r"tolov",
        r"o'tkazma", r"otkazma", r"payment", r"transfer",
    ],
    "cards": [
        r"карт", r"humo", r"uzcard", r"visa", r"master", r"karta", r"card",
    ],
    "cashback": [
        r"кэшбэк", r"кешбек", r"cashback", r"cash back", r"кэшбек", r"bonus",
        r"бонус", r"cashbek",
    ],
    "support": [
        r"поддержк", r"поддержка", r"оператор", r"чат", r"колл", r"support",
        r"help", r"жалоб", r"service", r"xizmat",
    ],
    "login_auth": [
        r"вход", r"парол", r"смс", r"sms", r"face.?id", r"биометр", r"авториз",
        r"login", r"pin", r"otp", r"код",
    ],
    "crashes": [
        r"вылет", r"краш", r"crash", r"зависа", r"тормоз", r"лаг", r"баг",
        r"ошибк", r"error", r"не работает", r"ishlamay", r"xato",
    ],
    "updates": [
        r"обновлен", r"update", r"версия", r"version", r"yangilanish",
    ],
    "loans_credit": [
        r"кредит", r"рассроч", r"микрозайм", r"заём", r"заем", r"loan",
        r"nasiya", r"nasiya", r"limit", r"лимит",
    ],
    "fees": [
        r"комисс", r"платн", r"дорог", r"fee", r"процент", r"foiz",
    ],
    "ui_ux": [
        r"интерфейс", r"дизайн", r"удобн", r"неудобн", r"ui", r"ux", r"красив",
        r"понятн", r"сложн",
    ],
}


def extract_themes(texts: list[str]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for text in texts:
        if not text:
            continue
        low = text.lower()
        for theme, patterns in THEME_PATTERNS.items():
            if any(re.search(p, low) for p in patterns):
                counts[theme] += 1
    total = sum(counts.values()) or 1
    return [
        {"theme": theme, "count": count, "share": round(count / total, 3)}
        for theme, count in counts.most_common()
    ]


def top_keywords(texts: list[str], *, limit: int = 40) -> list[dict[str, Any]]:
    token_re = re.compile(r"[a-zA-Zа-яА-ЯёЁўқғҳʼ'’-]{3,}")
    counter: Counter[str] = Counter()
    for text in texts:
        if not text:
            continue
        for tok in token_re.findall(text.lower()):
            t = tok.strip("-'")
            if len(t) < 3 or t in STOPWORDS:
                continue
            counter[t] += 1
    return [{"word": w, "count": c} for w, c in counter.most_common(limit)]


def enrich_dashboard(stats: dict[str, Any]) -> dict[str, Any]:
    sample = stats.get("keyword_sample") or []
    texts = [s.get("body") or "" for s in sample]
    neg_texts = [s.get("body") or "" for s in sample if (s.get("rating") or 5) <= 2]
    pos_texts = [s.get("body") or "" for s in sample if (s.get("rating") or 0) >= 4]

    stats["themes"] = extract_themes(texts)
    stats["themes_negative"] = extract_themes(neg_texts)
    stats["keywords"] = top_keywords(texts)
    stats["keywords_negative"] = top_keywords(neg_texts, limit=25)
    stats["keywords_positive"] = top_keywords(pos_texts, limit=25)

    # Drop bulky sample from API response
    stats.pop("keyword_sample", None)
    return stats
