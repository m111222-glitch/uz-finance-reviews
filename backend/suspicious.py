"""Flag 4-5★ reviews that look like bulk/paid reviews, with the evidence.

Heuristics, not proof: each review gets points for observable signals and is
flagged at FLAG_SCORE, and only with evidence of coordination (a campaign of
similar names within a week, or a repeated text). One odd review never flags:
real people pick odd nicknames. Signals came from patterns seen in the wild:
  - AVO, Hamkorbank: generated Western-style App Store names ("Payne Frieda",
    "BartonVirginiau", "Lucia_Leonoro"), generic praise, repeats, bursts.
  - Listee: Russian names writing long, polished Uzbek-Latin stories.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

FLAG_SCORE = 3

REASONS = (
    "generated_name",   # App Store nickname that looks like a generated Western name
    "name_campaign",    # 3+ such names in the app within a week, and a quarter of its 4-5★ reviews
    "ru_name_uz_text",  # Russian name writing in Uzbek (Latin)
    "duplicate_text",   # same or near-identical text as another author
    "burst",            # several 4-5★ reviews within hours, far above the app's pace
    "long_praise",      # long story-style praise
    "mixed_title",      # App Store title and text in different languages
)

# --- names --------------------------------------------------------------------

LOCAL_SUFFIXES = (
    "bek", "jon", "xon", "khon", "boy", "bay", "mirza", "iddin", "uddin", "ullo", "ulla",
    "zoda", "zod", "oy", "ov", "ova", "ev", "eva", "yev", "yeva", "iev", "ieva", "ovich",
    "evich", "ovna", "evna", "ayev", "ayeva", "aev", "aeva", "baev", "bayev", "qul", "kul",
    "nazar", "murod", "ali", "shoh", "shox", "niso", "gul", "bonu", "bibi",
    # Russian/Ukrainian surname and diminutive endings ("garik", "mowniy", "Tati_shka", "Rudenko")
    "ik", "iy", "yy", "ich", "shka", "enko", "chuk", "yuk",
    "бек", "жон", "хон", "бой", "мирза", "иддин", "улло", "зода", "ов", "ова", "ев", "ева",
    "ович", "евич", "овна", "евна", "кул", "қул", "гул", "али", "шох", "нисо",
)
LOCAL_NAMES = {
    # Uzbek / Tajik given names often written without a telltale suffix
    "aziz", "bobur", "babur", "dilshod", "jasur", "sardor", "shahzod", "doniyor", "sanjar",
    "javohir", "javlon", "rustam", "farrux", "farrukh", "madina", "dilnoza", "nilufar",
    "shoira", "zarina", "gulnora", "malika", "sevara", "kamola", "nodira", "feruza",
    "muhammad", "mukhammad", "abdulla", "islom", "akmal", "anvar", "bahodir", "bakhodir",
    "botir", "temur", "timur", "shoxrux", "shokhrukh", "xurshida", "mohira", "umid",
    "otabek", "ulugbek", "nodir", "said", "sherzod", "sherali", "elyor", "jamshid", "sarvar",
    "ilhom", "ravshan", "rasul", "olim", "zafar", "sabina", "dildora", "lola", "laylo",
    "yulduz", "barno", "saida", "aziza", "munisa", "shahlo", "rano", "kamol", "behruz",
    "abdurahmon", "abdulaziz", "firdavs", "mirjalol", "asadbek", "diyor", "nurislom",
    "abush", "urol", "sunnat", "shamsiddin", "quranbay",
    # Koryo-saram (Korean-Uzbek) surnames
    "kim", "li", "lee", "pak", "park", "tsoy", "tsoi", "choi", "ten", "khegay", "kegay",
    "ligay", "shin", "yan", "kan", "nam", "ogay", "ogai", "kogay", "tyan", "khvan", "hwang",
    "em", "ni", "ugay", "tskhay", "pyagay",
    # Cities and words people put in nicknames
    "navoiy", "termiz", "tashkent", "toshkent", "samarkand", "samarqand", "bukhara", "buxoro",
    "andijan", "andijon", "namangan", "fergana", "nukus", "urgench", "jizzakh", "gulistan",
    "karshi", "qarshi", "kokand", "margilan", "chirchik", "angren", "almalyk", "dushanbe",
    "khujand", "user", "unknown", "account", "super", "top", "aka", "opa", "official",
    # Uzbek and Russian words people use as nicknames ("Rost ekan", "dydya Vasya")
    "ekan", "rost", "olloh", "ollohga", "alloh", "onson", "oson", "bola", "dost", "brat",
    "bratan", "paren", "dyadya", "dydya", "tyotya", "ibragim", "ibrahim", "abik",
    "khan", "hali", "chotki", "zarifa", "sayyora", "kozim", "zor", "zur", "yaxshi", "ajoyib",
}
RUSSIAN_NAMES = {
    # Cyrillic and common Latin spellings; used to spot "Russian name, Uzbek text"
    "александр", "алексей", "андрей", "антон", "артём", "артем", "борис", "вадим", "валентин",
    "василий", "виктор", "владимир", "владислав", "вячеслав", "геннадий", "георгий", "глеб",
    "григорий", "даниил", "денис", "дмитрий", "евгений", "егор", "елисей", "иван", "игорь",
    "илья", "кирилл", "константин", "лев", "леонид", "максим", "матвей", "михаил", "никита",
    "николай", "олег", "павел", "пётр", "петр", "роман", "семён", "семен", "сергей",
    "станислав", "степан", "тимофей", "фёдор", "федор", "юрий", "ярослав", "дамир",
    "александра", "алина", "алла", "анастасия", "ангелина", "анна", "валентина", "валерия",
    "вера", "вероника", "виктория", "галина", "дарья", "диана", "ева", "евгения", "екатерина",
    "елена", "елизавета", "жанна", "зоя", "инна", "ирина", "карина", "кристина", "ксения",
    "лариса", "лидия", "любовь", "людмила", "маргарита", "марина", "мария", "надежда",
    "наталья", "наталия", "нина", "оксана", "олеся", "ольга", "полина", "светлана", "софия",
    "софья", "тамара", "татьяна", "ульяна", "юлия", "яна",
    "aleksandr", "alexander", "aleksey", "alexey", "andrey", "andrei", "anton", "artem",
    "boris", "vadim", "viktor", "victor", "vladimir", "vladislav", "dmitriy", "dmitry",
    "evgeniy", "evgeny", "egor", "elisey", "ivan", "igor", "ilya", "kirill", "konstantin",
    "maksim", "maxim", "mikhail", "nikita", "nikolay", "oleg", "pavel", "roman", "sergey",
    "sergei", "stanislav", "yuriy", "yuri", "anastasia", "anna", "darya", "daria",
    "ekaterina", "elena", "irina", "kristina", "ksenia", "marina", "mariya", "maria",
    "natalia", "natalya", "oksana", "olga", "polina", "svetlana", "tatiana", "tatyana",
    "yulia", "yuliya", "viktoria", "victoria", "gleb", "stas", "anastasiya", "denis",
    "artyom", "danil", "daniil", "timofey", "matvey", "arseniy", "egor", "yegor", "vlad",
    "sasha", "dima", "lena", "katya", "masha", "nastya", "olya", "tanya", "sveta", "ira",
    "nadezhda", "lyudmila", "galina", "valentina", "veronika", "alina", "karina", "diana",
    "valeriya", "alisa", "sofia", "sofya", "eva", "vera", "zoya", "inna", "rita", "larisa",
    "vasya", "petya", "kolya", "senya", "ksenya", "ksyusha", "katerina", "katerinaa", "tati",
    "zhenya", "misha", "pasha", "seryozha", "lyosha", "garik",
}

NAME_SPLIT = re.compile(r"[\s_.\-]+")
CAMEL_SPLIT = re.compile(r"(?<=[a-z])(?=[A-Z])")


def _name_tokens(author: str) -> list[str]:
    parts = []
    for chunk in NAME_SPLIT.split(author.strip()):
        parts += [p for p in CAMEL_SPLIT.split(chunk) if p]
    return [p for p in parts if not p.isdigit()]


def _is_local_token(tok: str) -> bool:
    t = tok.lower()
    if t in LOCAL_NAMES or t in RUSSIAN_NAMES:
        return True
    # q, x, oʻ/gʻ and "yy" (Sayyora, Tayyor) are typical of Uzbek and rare in Western names;
    # so are Abd- names and verb endings in phrase-nicknames ("Hali bilmadim", "Chotki ishlavoti")
    if re.search(r"[qxʻ‘'ўқғҳ]|yy|^abd|(?:madim|yapti|voti|moq)$", t):
        return True
    return any(t.endswith(s) and len(t) > len(s) + 1 for s in LOCAL_SUFFIXES)


def foreign_style_name(author: str | None) -> bool:
    """Two Latin name-like words, neither looking Uzbek, Tajik or Russian."""
    # Dots and long digit runs mark handles ("swise.tech", "klient2024"), not names
    if not author or re.search(r"[^\x00-\x7f]|\.|\d{3,}", author):
        return False
    toks = _name_tokens(author)
    # Generated names use full first and last names; short parts ("Ant", "zor") are nickname bits
    if len(toks) != 2 or not all(t.isalpha() and len(t) >= 4 for t in toks):
        return False
    return not any(_is_local_token(t) for t in toks)


def russian_first_name(author: str | None) -> bool:
    toks = _name_tokens(author or "")
    return bool(toks) and toks[0].lower() in RUSSIAN_NAMES


# --- text ---------------------------------------------------------------------

UZ_LATIN_WORDS = re.compile(
    r"\b(va|uchun|juda|bilan|ham|men|menga|edi|emas|lekin|kerak|ilova\w*|yaxshi|qulay|"
    r"hammasi|bo['ʻ‘]l\w*|qil\w*|ekan|endi|faqat|ko['ʻ‘]p|tez\w*|oson|qaror|topdim|"
    r"o['ʻ‘]rnat\w*|sotib|narx\w*|e['ʻ‘]lon\w*|xizmat\w*|sodda|foydali|ajoyib|ishonchli|"
    r"omonat\w*|karta\w*|barqaror|tajriba|yechim|joyida|rahmat|ochish|yo['ʻ‘]q|bor)\b",
    re.I,
)
RU_WORDS = re.compile(
    r"\b(и|в|не|на|что|это|очень|приложение|все|всё|как|для|но|по|спасибо|удобно|"
    r"удобное|работает|отлично|хорошее|можно)\b",
    re.I,
)


def text_language(text: str | None, *, short: bool = False) -> str | None:
    """Rough language of a text: "uz", "ru" or "latin"; `short` (titles) needs fewer cues."""
    t = text or ""
    latin = len(re.findall(r"[a-zA-Z]", t))
    cyr = len(re.findall(r"[а-яА-ЯёЁўқғҳЎҚҒҲ]", t))
    if latin + cyr < 3:
        return None
    if latin >= cyr:
        hits = len(UZ_LATIN_WORDS.findall(t))
        return "uz" if hits >= (1 if short else 2) or re.search(r"[og]['ʻ‘]", t) else "latin"
    return "ru" if len(RU_WORDS.findall(t)) >= 1 or not re.search(r"[ўқғҳ]", t, re.I) else "uz"


def _normalize(text: str | None) -> str:
    t = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def _words(text: str | None) -> list[str]:
    return _normalize(text).split()


# --- scoring ------------------------------------------------------------------


def _parse(dt: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((dt or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _near(t: datetime | None, sorted_times: list[datetime], hours: float) -> int:
    """How many of sorted_times fall within ±hours of t."""
    if not t:
        return 0
    d = timedelta(hours=hours)
    return bisect_right(sorted_times, t + d) - bisect_left(sorted_times, t - d)


def score_reviews(reviews: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Score 4-5★ reviews; returns {review_id: {"score", "reasons", "flagged"}}.

    Reasons are codes (see REASONS) so each channel can word them in its language.

    Pass every review of the apps involved: repeats, bursts and campaigns are
    judged against the app's other reviews, and phrase rarity across all apps.
    """
    # Stock phrases ("juda tez va qulay") recur across apps from real people;
    # a repeat only counts when the text is rare overall
    phrase_count: dict[str, int] = defaultdict(int)
    for r in reviews:
        phrase_count[_normalize(r.get("body"))] += 1

    by_app: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in reviews:
        by_app[(r["app_slug"], r["store"])].append(r)

    out: dict[str, dict[str, Any]] = {}
    for (_slug, store), rows in by_app.items():
        positive = [r for r in rows if r.get("rating") in (4, 5) and _parse(r.get("review_date"))]
        when = {r["id"]: _parse(r["review_date"]) for r in positive}

        # Same text from different authors: exact (if rare overall) or near-identical long texts
        texts = [(r, _normalize(r.get("body")), set(_words(r.get("body")))) for r in positive]
        copies: dict[str, list[tuple[str, datetime]]] = defaultdict(list)
        for r, norm, _ in texts:
            copies[norm].append(((r.get("author") or "").lower(), when[r["id"]]))
        index: dict[str, list[int]] = defaultdict(list)
        keys = []
        for i, (_r, _norm, ws) in enumerate(texts):
            top = sorted(ws, key=len, reverse=True)[:3] if len(ws) >= 8 else []
            keys.append(top)
            for w in top:
                index[w].append(i)
        dup: dict[str, int] = {}  # review id -> points
        for i, (r, norm, ws) in enumerate(texts):
            n = len(norm.split())
            me = (r.get("author") or "").lower()
            other_copies = [t for a, t in copies[norm] if a != me] if n >= 4 and phrase_count[norm] <= 4 else []
            near = False
            for j in {j for w in keys[i] for j in index[w]} - {i}:
                o, _onorm, ows = texts[j]
                if (o.get("author") or "").lower() != me and len(ws & ows) / len(ws | ows) >= 0.85:
                    near = True
                    break
            if not (other_copies or near):
                continue
            # Short phrases can repeat by chance; copies within the hour or long texts can't
            within_hour = any(abs((t - when[r["id"]]).total_seconds()) <= 3600 for t in other_copies)
            dup[r["id"]] = 3 if n >= 8 else 2 if (n >= 6 or within_hour) else 1

        # Bursts: 4+ positive reviews in 6 hours, at least 4x this app's pace over the surrounding month
        times = sorted(t for t in when.values() if t)
        burst_ids = set()
        for r in positive:
            t = when[r["id"]]
            k = _near(t, times, 3)
            month_rate_6h = _near(t, times, 15 * 24) / (30 * 4)
            if k >= 4 and k >= 4 * max(month_rate_6h, 0.25):
                burst_ids.add(r["id"])

        # App Store nicknames are free-form, so generated Western names stand out there;
        # Google account names are messy enough ("Maruf Maruf", "Lord King") to cause false alarms
        foreign = {r["id"] for r in positive if store == "ios" and foreign_style_name(r.get("author"))}
        ru_uz = {
            r["id"] for r in positive
            if russian_first_name(r.get("author"))
            and text_language(r.get("body")) == "uz"
            and re.search(r"[a-zA-Z]", r.get("body") or "")
        }
        foreign_times = sorted(when[i] for i in foreign)
        ru_uz_times = sorted(when[i] for i in ru_uz)

        for r in positive:
            reasons: list[tuple[str, int]] = []
            lang = text_language(r.get("body"))
            # An odd name alone is weak (real people pick odd nicknames); what marks bulk
            # reviews is many of the same kind in one app within a week
            # and a sizeable share of its positive reviews that week, not a few among hundreds
            week_positive = _near(when[r["id"]], times, 7 * 24)
            for ids, kind_times, code in ((foreign, foreign_times, "generated_name"), (ru_uz, ru_uz_times, "ru_name_uz_text")):
                if r["id"] in ids:
                    reasons.append((code, 1))
                    same_kind = _near(when[r["id"]], kind_times, 7 * 24)
                    if same_kind >= 3 and same_kind * 4 >= week_positive and ("name_campaign", 2) not in reasons:
                        reasons.append(("name_campaign", 2))
            if r["id"] in dup:
                reasons.append(("duplicate_text", dup[r["id"]]))
            if r["id"] in burst_ids:
                reasons.append(("burst", 1))
            if len(_words(r.get("body"))) >= 25:
                reasons.append(("long_praise", 1))
            title_lang = text_language(r.get("title"), short=True)
            if title_lang and lang and title_lang != lang and {title_lang, lang} <= {"uz", "ru"}:
                reasons.append(("mixed_title", 1))
            score = sum(p for _, p in reasons)
            codes = [name for name, _ in reasons]
            # Bulk reviews are coordinated: require a campaign or a repeated text, never just an odd review
            coordinated = "name_campaign" in codes or "duplicate_text" in codes
            out[r["id"]] = {
                "score": score,
                "reasons": codes,
                "flagged": score >= FLAG_SCORE and coordinated,
            }
    return out
