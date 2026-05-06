from datetime import date
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import re


OCR_DIGIT_TRANSLATION = str.maketrans(
    {
        "O": "0",
        "o": "0",
        "О": "0",
        "о": "0",
        "I": "1",
        "l": "1",
        "|": "1",
        "S": "5",
        "s": "5",
        "B": "8",
    }
)

MONTHS = {
    "jan": 1,
    "january": 1,
    "янв": 1,
    "января": 1,
    "feb": 2,
    "february": 2,
    "фев": 2,
    "февраля": 2,
    "mar": 3,
    "march": 3,
    "мар": 3,
    "марта": 3,
    "apr": 4,
    "april": 4,
    "апр": 4,
    "апреля": 4,
    "may": 5,
    "мая": 5,
    "jun": 6,
    "june": 6,
    "июн": 6,
    "июня": 6,
    "jul": 7,
    "july": 7,
    "июл": 7,
    "июля": 7,
    "aug": 8,
    "august": 8,
    "авг": 8,
    "августа": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "сен": 9,
    "сентября": 9,
    "oct": 10,
    "october": 10,
    "окт": 10,
    "октября": 10,
    "nov": 11,
    "november": 11,
    "ноя": 11,
    "ноября": 11,
    "dec": 12,
    "december": 12,
    "дек": 12,
    "декабря": 12,
}


def parse_decimal(value):
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))

    text = str(value).strip()
    if not text or text.lower() in {"n/a", "na", "none", "null", "-"}:
        return None

    text = text.translate(OCR_DIGIT_TRANSLATION)
    text = re.sub(r"[^\d,.\-]", "", text)
    if not text:
        return None

    comma = text.rfind(",")
    dot = text.rfind(".")
    if comma > dot:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")

    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def normalize_code(value):
    if value is None:
        return ""
    text = str(value).strip().upper()
    text = re.sub(r"^(NO|N|№|PO|P\.O\.|INVOICE|INV|DATE|REF)[:#\s.-]+", "", text)
    return re.sub(r"[^A-Z0-9]", "", text)


def normalize_text(value):
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = text.replace("ё", "е")
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def normalize_company(value):
    text = normalize_text(value)
    if not text:
        return ""

    stop_words = {
        "co",
        "company",
        "corp",
        "corporation",
        "inc",
        "ltd",
        "limited",
        "llc",
        "llp",
        "nv",
        "n",
        "v",
        "ооо",
        "ао",
        "тоо",
    }
    words = [word for word in text.split() if word not in stop_words]
    return " ".join(words)


def normalize_currency(value):
    aliases = {
        "$": "USD",
        "US": "USD",
        "US$": "USD",
        "USDOLLAR": "USD",
        "DOLLAR": "USD",
        "DOLLARS": "USD",
        "€": "EUR",
        "EURO": "EUR",
        "RMB": "CNY",
        "YUAN": "CNY",
        "CNY": "CNY",
        "KZT": "KZT",
        "TENGE": "KZT",
    }
    raw = str(value).strip().upper()
    if raw in aliases:
        return aliases[raw]

    text = normalize_code(value)
    if not text:
        return ""

    return aliases.get(raw, aliases.get(text, text))


def normalize_incoterms(value):
    text = normalize_code(value)
    if not text:
        return ""

    codes = {
        "EXW",
        "FCA",
        "FAS",
        "FOB",
        "CFR",
        "CIF",
        "CPT",
        "CIP",
        "DAP",
        "DPU",
        "DDP",
        "DAT",
        "DAF",
        "DES",
        "DEQ",
        "DDU",
    }
    for code in codes:
        if text.startswith(code):
            return code
    return text


def normalize_date(value):
    if value is None:
        return ""

    text = str(value).strip().lower()
    if not text or text in {"n/a", "na", "none", "null", "-"}:
        return ""

    text = text.translate(OCR_DIGIT_TRANSLATION)
    text = text.replace(",", " ")
    text = re.sub(r"\s+", " ", text)

    numeric = _parse_numeric_date(text)
    if numeric:
        return numeric.isoformat()

    named = _parse_named_month_date(text)
    if named:
        return named.isoformat()

    return ""


def similarity(left, right):
    left_text = normalize_text(left)
    right_text = normalize_text(right)
    if not left_text or not right_text:
        return 0
    if left_text.startswith(right_text) or right_text.startswith(left_text):
        return 1
    return SequenceMatcher(None, left_text, right_text).ratio()


def company_similarity(left, right):
    left_text = normalize_company(left)
    right_text = normalize_company(right)
    if not left_text or not right_text:
        return 0
    if left_text.startswith(right_text) or right_text.startswith(left_text):
        return 1
    return SequenceMatcher(None, left_text, right_text).ratio()


def product_similarity(left, right):
    left_text = normalize_text(left)
    right_text = normalize_text(right)
    if not left_text or not right_text:
        return 0
    if left_text.startswith(right_text) or right_text.startswith(left_text):
        return 1

    sequence_score = SequenceMatcher(None, left_text, right_text).ratio()
    left_tokens = _product_tokens(left_text)
    right_tokens = _product_tokens(right_text)
    if not left_tokens or not right_tokens:
        return sequence_score

    overlap = len(left_tokens & right_tokens)
    coverage = overlap / min(len(left_tokens), len(right_tokens))
    return max(sequence_score, coverage)


def ocr_suspect(*values):
    for value in values:
        if value is None:
            continue
        text = str(value)
        if re.search(r"\d[\s,.\-]*[OoОоIl|SsB]|[OoОоIl|SsB][\s,.\-]*\d", text):
            return True
    return False


def _parse_numeric_date(text):
    patterns = [
        (r"\b(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\b", "ymd"),
        (r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b", "dmy"),
        (r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2})\b", "dmy_short"),
    ]
    for pattern, kind in patterns:
        match = re.search(pattern, text)
        if not match:
            continue

        first, second, third = [int(part) for part in match.groups()]
        if kind == "ymd":
            return _safe_date(first, second, third)
        if kind == "dmy":
            return _safe_date(third, second, first)
        if kind == "dmy_short":
            year = 2000 + third if third < 70 else 1900 + third
            return _safe_date(year, second, first)

    return None


def _parse_named_month_date(text):
    tokens = re.findall(r"\d{1,4}|[a-zа-я]+", text, flags=re.UNICODE)
    for index, token in enumerate(tokens):
        month = MONTHS.get(token)
        if not month:
            continue

        before = _nearest_number(tokens[:index], reverse=True)
        after = _nearest_number(tokens[index + 1 :], reverse=False)
        if before is None or after is None:
            continue

        if before > 31:
            year, day = before, after
        else:
            day, year = before, after

        if year < 100:
            year = 2000 + year if year < 70 else 1900 + year

        parsed = _safe_date(year, month, day)
        if parsed:
            return parsed

    return None


def _nearest_number(tokens, reverse):
    iterable = reversed(tokens) if reverse else tokens
    for token in iterable:
        if str(token).isdigit():
            return int(token)
    return None


def _safe_date(year, month, day):
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _product_tokens(text):
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "item",
        "description",
        "vba",
        "fb",
        "fl",
        "cl",
    }
    tokens = set()
    for token in re.findall(r"[a-zа-я]+|\d+[a-z]*", text, flags=re.UNICODE):
        if token in stop_words or len(token) < 2:
            continue
        if token.endswith("s") and len(token) > 3:
            token = token[:-1]
        tokens.add(token)
    return tokens
