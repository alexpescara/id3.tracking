import re


POSITIVE_129 = [
    r"\b12[,.]9\s*(?:pollici|\"|''|inch|in)\b",
    r"\b12[,.]9\b",
    r"12,9.?display",
    r"12.9.?display",
    r"nuovo infotainment",
]

NEGATIVE_129 = [
    r"\b12\s*(?:pollici|\"|inch)\b",
    r"\b10\s*(?:pollici|\"|inch)\b",
]


def classify_listing(item: dict) -> dict:
    text = " ".join(
        str(item.get(k) or "")
        for k in ("title", "description")
    ).lower()

    score = 0
    evidence = []

    for pattern in POSITIVE_129:
        if re.search(pattern, text, re.I):
            score += 30
            evidence.append(pattern)

    for pattern in NEGATIVE_129:
        if re.search(pattern, text, re.I):
            score -= 20

    year = item.get("registration_year")
    battery = item.get("battery_kwh")

    if year and int(year) >= 2024:
        score += 20

    if battery and float(battery) >= 58:
        score += 15

    score = max(0, min(100, score))

    item["restyling_candidate"] = bool(year and int(year) >= 2024)
    item["infotainment_129_candidate"] = score >= 50
    item["confidence_score"] = score
    item["classification_evidence"] = "; ".join(evidence)

    return item
