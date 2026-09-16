import re
from typing import Any


# ============================================================
# PATTERN POSITIVI
# ============================================================

POSITIVE_129 = [
    # Formati espliciti
    (
        r"\b12[,.]9\s*(?:pollici|"
        r"\"|''|inch|in)\b",
        "display 12,9 pollici",
        70,
    ),
    (
        r"\b12[,.]9\s*(?:\"|''|"
        r"pollici|inch|in)\b",
        "display 12,9",
        70,
    ),
    (
        r"\b12[,.]9\b",
        "display 12,9",
        60,
    ),

    # Espressioni relative all'infotainment
    (
        r"12[,.]9.{0,30}"
        r"(?:display|schermo|touchscreen|"
        r"infotainment)",
        "display 12,9 + infotainment",
        75,
    ),
    (
        r"(?:display|schermo|touchscreen|"
        r"infotainment).{0,30}"
        r"12[,.]9",
        "infotainment + display 12,9",
        75,
    ),

    # Nuovo infotainment.
    # Questo da solo non dimostra necessariamente
    # il 12,9", quindi assegniamo un punteggio inferiore.
    (
        r"nuovo\s+infotainment",
        "nuovo infotainment",
        35,
    ),
    (
        r"nuovo\s+sistema\s+infotainment",
        "nuovo sistema infotainment",
        35,
    ),
]


# ============================================================
# PATTERN NEGATIVI
# ============================================================

NEGATIVE_129 = [
    (
        r"\b12\s*(?:pollici|\"|''|inch)\b",
        "display 12 pollici",
        -60,
    ),
    (
        r"\b10\s*(?:pollici|\"|''|inch)\b",
        "display 10 pollici",
        -70,
    ),
    (
        r"\b10[,.]25\s*(?:pollici|\"|''|inch)\b",
        "display 10,25 pollici",
        -70,
    ),
]


# ============================================================
# UTILITY
# ============================================================

def _clean_text(value: Any) -> str:
    """
    Normalizza un valore testuale.
    """

    if value is None:
        return ""

    text = str(value)

    text = text.replace(
        "\xa0",
        " ",
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def _build_classification_text(
    item: dict,
) -> str:
    """
    Costruisce il testo utilizzato dal classificatore.

    Utilizziamo titolo, descrizione ed equipment,
    ma NON l'intero testo della pagina AutoScout24.
    """

    fields = [
        item.get("title"),
        item.get("description"),
        item.get("equipment"),
    ]

    values = []

    for value in fields:
        value = _clean_text(value)

        if value:
            values.append(value)

    return " ".join(
        values
    )


def _safe_year(
    value: Any,
) -> int | None:
    """
    Converte l'anno in modo robusto.
    """

    if value is None:
        return None

    try:
        return int(
            float(value)
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


def _safe_battery(
    value: Any,
) -> float | None:
    """
    Converte la batteria in modo robusto.
    """

    if value is None:
        return None

    try:
        return float(value)
    except (
        TypeError,
        ValueError,
    ):
        return None


# ============================================================
# CLASSIFICAZIONE INFOTAINMENT 12,9"
# ============================================================

def _classify_infotainment_129(
    text: str,
) -> tuple[
    bool | None,
    int,
    list[str],
]:
    """
    Classifica la probabilità che l'auto disponga
    dell'infotainment/display da 12,9".

    Restituisce:

        True
            evidenza positiva

        False
            evidenza negativa esplicita

        None
            informazione insufficiente

    Il punteggio rappresenta la confidenza
    della classificazione e NON la qualità dell'auto.
    """

    score = 0
    positive_evidence = []
    negative_evidence = []

    # --------------------------------------------------------
    # Evidenze positive
    # --------------------------------------------------------

    for (
        pattern,
        description,
        points,
    ) in POSITIVE_129:

        if re.search(
            pattern,
            text,
            re.IGNORECASE,
        ):
            score += points

            if description not in positive_evidence:
                positive_evidence.append(
                    description
                )

    # --------------------------------------------------------
    # Evidenze negative
    # --------------------------------------------------------

    negative_score = 0

    for (
        pattern,
        description,
        points,
    ) in NEGATIVE_129:

        if re.search(
            pattern,
            text,
            re.IGNORECASE,
        ):
            negative_score += abs(
                points
            )

            if description not in negative_evidence:
                negative_evidence.append(
                    description
                )

    # --------------------------------------------------------
    # Decisione
    # --------------------------------------------------------

    # Evidenza negativa esplicita:
    # non possiamo considerare 12,9" presente.
    if negative_score > 0 and score < 60:
        evidence = (
            negative_evidence
            + positive_evidence
        )

        return (
            False,
            min(
                100,
                negative_score,
            ),
            evidence,
        )

    # Evidenza positiva forte.
    if score >= 60:
        return (
            True,
            min(
                100,
                score,
            ),
            positive_evidence,
        )

    # "Nuovo infotainment" da solo NON basta
    # per affermare che il display sia 12,9".
    if positive_evidence:
        return (
            None,
            min(
                100,
                score,
            ),
            positive_evidence,
        )

    # Nessuna informazione.
    return (
        None,
        0,
        [],
    )


# ============================================================
# CLASSIFICAZIONE RESTYLING
# ============================================================

def _classify_restyling(
    item: dict,
    infotainment_candidate: bool | None,
    infotainment_evidence: list[str],
) -> bool | None:
    """
    Determina se esistono elementi sufficienti per considerare
    l'auto una candidata al restyling.

    IMPORTANTE:
    l'anno 2024 da solo NON implica restyling.

    Restituiamo quindi:

        True
            quando esiste un'indicazione concreta

        False
            quando esiste un'indicazione esplicita contraria

        None
            quando non abbiamo informazioni sufficienti
    """

    text = _build_classification_text(
        item
    ).lower()

    # Evidenze positive esplicite
    restyling_patterns = [
        r"\brestyling\b",
        r"\bfacelift\b",
        r"\bnuova generazione\b",
        r"\bnuovo infotainment\b",
        r"\bnuovo sistema infotainment\b",
        r"\b12[,.]9\b",
    ]

    for pattern in restyling_patterns:

        if re.search(
            pattern,
            text,
            re.IGNORECASE,
        ):
            return True

    # Un display 12,9" riconosciuto costituisce
    # una forte indicazione per la nostra classificazione.
    if infotainment_candidate is True:
        return True

    # Non abbiamo elementi sufficienti.
    return None


# ============================================================
# CLASSIFICAZIONE PRINCIPALE
# ============================================================

def classify_listing(
    item: dict,
) -> dict:
    """
    Classifica un annuncio Volkswagen ID.3.

    Campi aggiunti:

        restyling_candidate
        infotainment_129_candidate
        confidence_score
        classification_evidence

    Nota:
    confidence_score riguarda esclusivamente la qualità
    dell'evidenza relativa al 12,9"/infotainment.

    NON rappresenta un punteggio dell'automobile.
    """

    text = _build_classification_text(
        item
    ).lower()

    # --------------------------------------------------------
    # Infotainment
    # --------------------------------------------------------

  
    scraper_candidate = item.get(
        "infotainment_129_candidate"
    )
    
    scraper_evidence = _clean_text(
        item.get("classification_evidence")
    )
    
    (
        infotainment_candidate,
        infotainment_score,
        infotainment_evidence,
    ) = _classify_infotainment_129(
        text
    )
    
    # --------------------------------------------------------
    # Manteniamo l'evidenza trovata direttamente dallo scraper
    # --------------------------------------------------------
    
    if scraper_candidate is True:
        infotainment_candidate = True
    
        if scraper_evidence:
            infotainment_evidence.insert(
                0,
                scraper_evidence,
            )
    
        infotainment_score = max(
            infotainment_score,
            70,
        )
    
    elif (
        scraper_candidate is False
        and infotainment_candidate is None
    ):
        infotainment_candidate = False
    
        if scraper_evidence:
            infotainment_evidence.insert(
                0,
                scraper_evidence,
            )
    
        infotainment_score = max(
            infotainment_score,
            60,
        )

    if scraper_candidate is True:
        infotainment_candidate = True
    
        if scraper_evidence:
            infotainment_evidence.insert(
                0,
                scraper_evidence,
            )
    
        infotainment_score = max(
            infotainment_score,
            70,
        )
    
    elif (
        scraper_candidate is False
        and infotainment_candidate is None
    ):
        infotainment_candidate = False
    
        if scraper_evidence:
            infotainment_evidence.insert(
                0,
                scraper_evidence,
            )
    
        infotainment_score = max(
            infotainment_score,
            60,
        )

    # --------------------------------------------------------
    # Restyling
    # --------------------------------------------------------

    restyling_candidate = _classify_restyling(
        item,
        infotainment_candidate,
        infotainment_evidence,
    )

    # --------------------------------------------------------
    # Evidenza finale
    # --------------------------------------------------------

    evidence = []

    for value in infotainment_evidence:

        if value not in evidence:
            evidence.append(
                value
            )

    # --------------------------------------------------------
    # Dati tecnici utili come contesto,
    # ma NON come prova del 12,9".
    # --------------------------------------------------------

    year = _safe_year(
        item.get(
            "registration_year"
        )
    )

    battery = _safe_battery(
        item.get(
            "battery_kwh"
        )
    )

    if year is not None:
        evidence.append(
            f"anno {year}"
        )

    if battery is not None:
        evidence.append(
            f"batteria {battery:g} kWh"
        )

    # --------------------------------------------------------
    # Aggiornamento item
    # --------------------------------------------------------

    item[
        "restyling_candidate"
    ] = restyling_candidate

    item[
        "infotainment_129_candidate"
    ] = infotainment_candidate

    item[
        "confidence_score"
    ] = infotainment_score

    item[
        "classification_evidence"
    ] = "; ".join(
        evidence
    )

    return item
