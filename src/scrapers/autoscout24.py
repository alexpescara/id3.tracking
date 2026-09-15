import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from .base import BaseScraper


# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------

# Chilometraggio scritto normalmente in italiano:
# 26.173 km
# 40.698 km
# 7.910 km
#
# Il punto viene trattato come separatore delle migliaia.
KM_RE = re.compile(
    r"\b(\d{1,3}(?:[.\s]\d{3})+|\d{4,6})\s*km\b",
    re.IGNORECASE,
)

# Alcune pagine possono riportare anche "7910 km".
KM_SIMPLE_RE = re.compile(
    r"\b(\d{4,6})\s*km\b",
    re.IGNORECASE,
)

YEAR_RE = re.compile(
    r"\b(20\d{2})\b"
)

# Batterie tipiche ID.3.
# Permettiamo anche valori non interi per essere più robusti.
BATTERY_RE = re.compile(
    r"\b("
    r"5[0-9]|"
    r"6[0-9]|"
    r"7[0-9]|"
    r"8[0-9]"
    r")\s*kWh\b",
    re.IGNORECASE,
)

# Potenza espressa in CV / PS / kW.
POWER_RE = re.compile(
    r"\b(\d{2,3}(?:[.,]\d+)?)\s*(CV|PS|kW)\b",
    re.IGNORECASE,
)

# Infotainment 12,9".
INFOTAINMENT_129_RE = re.compile(
    r"""
    (?:
        \b12[\.,]\s*9\s*(?:["”“″]|pollici|inch)?
        |
        \b12[\.,]9\b
        |
        \b12\s+9\s*(?:["”“″]|pollici|inch)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Display da 12" / 12 pollici.
INFOTAINMENT_12_RE = re.compile(
    r"""
    (?:
        \b12\s*(?:["”“″]|pollici|inch)
        |
        \bdisplay\s+(?:touchscreen\s+)?da\s+12
        |
        \bschermo\s+(?:touchscreen\s+)?da\s+12
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


class AutoScout24Scraper(BaseScraper):
    """
    Scraper conservativo per le pagine pubbliche di AutoScout24.

    Priorità:
    1. dati strutturati (__NEXT_DATA__);
    2. JSON-LD;
    3. testo della pagina come fallback.

    Il prezzo NON viene mai estratto genericamente dall'intero testo:
    viene utilizzato soltanto un campo strutturato quando disponibile.

    Il scraper non tenta di aggirare CAPTCHA, login o sistemi anti-bot.
    """

    def search(self, search_url: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        scraper_cfg = self.config["scraper"]

        with sync_playwright() as p:

            browser = p.chromium.launch(
                headless=scraper_cfg.get(
                    "headless",
                    True,
                )
            )

            context = browser.new_context(
                user_agent=scraper_cfg.get(
                    "user_agent"
                ),
                locale="it-IT",
                viewport={
                    "width": 1440,
                    "height": 1000,
                },
            )

            page = context.new_page()

            page.set_default_timeout(
                scraper_cfg.get(
                    "timeout_ms",
                    30000,
                )
            )

            try:

                print(
                    f"[AutoScout24] Apertura: {search_url}"
                )

                page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                )

                page.wait_for_timeout(2500)

                self._dismiss_common_consent(page)

                max_pages = int(
                    scraper_cfg.get(
                        "max_pages",
                        1,
                    )
                )

                for page_no in range(max_pages):

                    print(
                        f"[AutoScout24] Elaborazione pagina "
                        f"{page_no + 1}/{max_pages}"
                    )

                    html = page.content()

                    page_results = (
                        self._parse_search_page(
                            html,
                            page.url,
                        )
                    )

                    print(
                        f"[AutoScout24] Annunci trovati nella pagina: "
                        f"{len(page_results)}"
                    )

                    results.extend(
                        page_results
                    )

                    if page_no + 1 >= max_pages:
                        break

                    next_link = page.locator(
                        'a[aria-label*="pagina successiva" i], '
                        'a[aria-label*="next" i], '
                        'a[title*="successiva" i]'
                    )

                    if next_link.count() == 0:
                        break

                    href = (
                        next_link.first.get_attribute(
                            "href"
                        )
                    )

                    if not href:
                        break

                    next_url = urljoin(
                        page.url,
                        href,
                    )

                    time.sleep(
                        float(
                            scraper_cfg.get(
                                "delay_seconds",
                                2.5,
                            )
                        )
                    )

                    page.goto(
                        next_url,
                        wait_until="domcontentloaded",
                    )

                    page.wait_for_timeout(1800)

            finally:

                context.close()
                browser.close()

        results = self._deduplicate(
            results
        )

        print(
            f"[AutoScout24] Totale annunci unici: "
            f"{len(results)}"
        )

        return results

    # ------------------------------------------------------------------
    # Cookie / consenso
    # ------------------------------------------------------------------

    @staticmethod
    def _dismiss_common_consent(page) -> None:

        selectors = [
            'button:has-text("Accetta tutto")',
            'button:has-text("Accetta")',
            'button:has-text("Accept all")',
            'button:has-text("Accept")',
        ]

        for selector in selectors:

            try:

                locator = page.locator(
                    selector
                )

                if locator.count():

                    locator.first.click(
                        timeout=1500
                    )

                    page.wait_for_timeout(
                        500
                    )

                    break

            except Exception:
                pass

    # ------------------------------------------------------------------
    # Parsing pagina
    # ------------------------------------------------------------------

    def _parse_search_page(
        self,
        html: str,
        source_url: str,
    ) -> list[dict[str, Any]]:

        soup = BeautifulSoup(
            html,
            "lxml",
        )

        cards: list[dict[str, Any]] = []

        # ==============================================================
        # 1. __NEXT_DATA__
        # ==============================================================

        next_data = (
            self._extract_next_data(
                soup
            )
        )

        if next_data is not None:

            candidates = (
                self._find_listing_objects(
                    next_data
                )
            )

            print(
                f"[AutoScout24] Oggetti strutturati trovati: "
                f"{len(candidates)}"
            )

            for obj in candidates:

                parsed = (
                    self._from_structured_object(
                        obj,
                        source_url,
                    )
                )

                if parsed.get("url"):
                    cards.append(
                        parsed
                    )

        # ==============================================================
        # 2. JSON-LD
        # ==============================================================

        for script in soup.find_all(
            "script",
            type="application/ld+json",
        ):

            raw_script = (
                script.string
                or script.get_text()
            )

            if not raw_script.strip():
                continue

            try:
                data = json.loads(
                    raw_script
                )

            except Exception:
                continue

            candidates = (
                data
                if isinstance(data, list)
                else [data]
            )

            for obj in candidates:

                if not isinstance(
                    obj,
                    dict,
                ):
                    continue

                obj_type = obj.get(
                    "@type"
                )

                if isinstance(
                    obj_type,
                    list,
                ):

                    valid_type = any(
                        x in {
                            "Car",
                            "Vehicle",
                            "Product",
                        }
                        for x in obj_type
                    )

                else:

                    valid_type = (
                        obj_type
                        in {
                            "Car",
                            "Vehicle",
                            "Product",
                        }
                    )

                if not valid_type:
                    continue

                parsed = (
                    self._from_jsonld(
                        obj,
                        source_url,
                    )
                )

                if parsed.get("url"):
                    cards.append(
                        parsed
                    )

        # ==============================================================
        # 3. Fallback HTML
        # ==============================================================

        if not cards:

            for a in soup.find_all(
                "a",
                href=True,
            ):

                href = a.get(
                    "href",
                    "",
                )

                text = " ".join(
                    a.stripped_strings
                )

                if "/annunci/" not in href:
                    continue

                if (
                    "id.3"
                    not in text.lower()
                ):
                    continue

                cards.append(
                    self._from_text(
                        text,
                        href,
                        source_url,
                    )
                )

        return [
            x
            for x in cards
            if x.get("url")
        ]

    # ------------------------------------------------------------------
    # __NEXT_DATA__
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_next_data(
        soup: BeautifulSoup,
    ):

        script = soup.find(
            "script",
            id="__NEXT_DATA__",
        )

        if script is None:
            return None

        raw = (
            script.string
            or script.get_text()
        )

        if not raw.strip():
            return None

        try:
            return json.loads(
                raw
            )

        except Exception:
            return None

    def _find_listing_objects(
        self,
        data: Any,
    ) -> list[dict[str, Any]]:

        found: list[dict[str, Any]] = []

        def walk(
            value: Any,
        ):

            if isinstance(
                value,
                dict,
            ):

                if self._looks_like_listing(
                    value
                ):
                    found.append(
                        value
                    )

                for child in value.values():
                    walk(child)

            elif isinstance(
                value,
                list,
            ):

                for child in value:
                    walk(child)

        walk(data)

        return found

    @staticmethod
    def _looks_like_listing(
        obj: dict[str, Any],
    ) -> bool:

        keys_lower = {
            str(k).lower()
            for k in obj.keys()
        }

        has_url = any(
            key in keys_lower
            for key in {
                "url",
                "detailurl",
                "href",
                "deeplink",
            }
        )

        has_price = any(
            key in keys_lower
            for key in {
                "price",
                "pricevalue",
                "priceamount",
                "amount",
            }
        )

        has_vehicle_data = any(
            key in keys_lower
            for key in {
                "mileage",
                "mileagefromodometer",
                "make",
                "model",
                "vehicle",
                "vehiclemodel",
                "registration",
                "firstregistration",
            }
        )

        return (
            has_url
            and has_price
            and has_vehicle_data
        )

    # ------------------------------------------------------------------
    # Dati strutturati
    # ------------------------------------------------------------------

    def _from_structured_object(
        self,
        obj: dict[str, Any],
        source_url: str,
    ) -> dict[str, Any]:

        url = self._first_value(
            obj,
            [
                "url",
                "detailUrl",
                "href",
                "deepLink",
                "deeplink",
            ],
        )

        if isinstance(
            url,
            dict,
        ):

            url = (
                url.get("href")
                or url.get("url")
            )

        if url:

            url = urljoin(
                source_url,
                str(url),
            )

        title = self._first_value(
            obj,
            [
                "name",
                "title",
                "displayName",
                "vehicleName",
            ],
        )

        price = self._first_value(
            obj,
            [
                "price",
                "priceValue",
                "priceAmount",
                "amount",
            ],
        )

        mileage = self._first_value(
            obj,
            [
                "mileage",
                "mileageValue",
                "mileageFromOdometer",
                "odometer",
            ],
        )

        year = self._first_value(
            obj,
            [
                "registrationYear",
                "firstRegistrationYear",
                "firstRegistration",
                "vehicleModelDate",
                "productionDate",
            ],
        )

        description = self._first_value(
            obj,
            [
                "description",
                "shortDescription",
                "subtitle",
            ],
        )

        seller = self._extract_seller(
            obj
        )

        raw = json.dumps(
            obj,
            ensure_ascii=False,
        )

        return self._normalise(
            {
                "url": url,
                "title": title
                or "Volkswagen ID.3",
                "description": (
                    description or ""
                ),
                "seller": seller,
                "price_raw": price,
                "mileage_raw": mileage,
                "year_raw": year,
                "raw": raw,
            }
        )

    @staticmethod
    def _first_value(
        obj: dict[str, Any],
        names: list[str],
    ):

        normalized = {
            str(k).lower(): v
            for k, v in obj.items()
        }

        for name in names:

            value = normalized.get(
                name.lower()
            )

            if value is not None:
                return value

        return None

    @staticmethod
    def _extract_seller(
        obj: dict[str, Any],
    ):

        seller = (
            obj.get("seller")
            or obj.get("dealer")
            or obj.get("sellerName")
            or obj.get("dealerName")
        )

        if isinstance(
            seller,
            dict,
        ):

            return (
                seller.get("name")
                or seller.get("legalName")
            )

        return seller

    # ------------------------------------------------------------------
    # JSON-LD
    # ------------------------------------------------------------------

    def _from_jsonld(
        self,
        obj: dict,
        source_url: str,
    ) -> dict:

        offers = (
            obj.get("offers")
            or {}
        )

        if isinstance(
            offers,
            list,
        ):

            offers = (
                offers[0]
                if offers
                else {}
            )

        url = (
            obj.get("url")
            or source_url
        )

        description = (
            obj.get("description")
            or ""
        )

        title = (
            obj.get("name")
            or "Volkswagen ID.3"
        )

        seller = (
            self._extract_jsonld_seller(
                obj
            )
        )

        price = None

        if isinstance(
            offers,
            dict,
        ):

            price = (
                offers.get("price")
                or offers.get(
                    "lowPrice"
                )
            )

        return self._normalise(
            {
                "url": url,
                "title": title,
                "description": description,
                "seller": seller,
                "price_raw": price,
                "mileage_raw": (
                    self._jsonld_mileage(
                        obj
                    )
                ),
                "year_raw": (
                    self._jsonld_year(
                        obj
                    )
                ),
                "raw": json.dumps(
                    obj,
                    ensure_ascii=False,
                ),
            }
        )

    @staticmethod
    def _extract_jsonld_seller(
        obj: dict,
    ):

        seller = obj.get(
            "seller"
        )

        if isinstance(
            seller,
            dict,
        ):

            return (
                seller.get("name")
                or seller.get("legalName")
            )

        return seller

    @staticmethod
    def _jsonld_mileage(
        obj: dict,
    ):

        mileage = obj.get(
            "mileageFromOdometer"
        )

        if isinstance(
            mileage,
            dict,
        ):

            return mileage.get(
                "value"
            )

        return mileage

    @staticmethod
    def _jsonld_year(
        obj: dict,
    ):

        return (
            obj.get(
                "vehicleModelDate"
            )
            or obj.get(
                "productionDate"
            )
        )

    # ------------------------------------------------------------------
    # Fallback testo
    # ------------------------------------------------------------------

    def _from_text(
        self,
        text: str,
        href: str,
        source_url: str,
    ) -> dict:

        return self._normalise(
            {
                "url": urljoin(
                    source_url,
                    href,
                ),
                "title": text[:200],
                "description": text,
                "price_raw": None,
                "mileage_raw": None,
                "year_raw": None,
                "seller": None,
                "raw": text,
            }
        )

    # ------------------------------------------------------------------
    # Normalizzazione
    # ------------------------------------------------------------------

    def _normalise(
        self,
        item: dict,
    ) -> dict:

        raw = item.get(
            "raw",
            "",
        )

        title = (
            item.get(
                "title",
                "",
            )
            or ""
        )

        description = (
            item.get(
                "description",
                "",
            )
            or ""
        )

        seller = item.get(
            "seller"
        )

        # Testo complessivo utilizzato SOLO per
        # fallback di km/anno/batteria/potenza/infotainment.
        combined = (
            f"{title} "
            f"{description} "
            f"{raw}"
        )

        # ==============================================================
        # PREZZO
        #
        # Il prezzo continua ad essere preso esclusivamente dai
        # dati strutturati.
        # ==============================================================

        price = self._extract_price(
            item.get(
                "price_raw"
            )
        )

        # ==============================================================
        # CHILOMETRAGGIO
        # ==============================================================

        mileage = self._extract_mileage(
            item.get(
                "mileage_raw"
            )
        )

        if mileage is None:

            match = KM_RE.search(
                combined
            )

            if match:

                mileage = (
                    self._parse_thousands_number(
                        match.group(1)
                    )
                )

        # ==============================================================
        # ANNO
        # ==============================================================

        year = self._extract_year(
            item.get(
                "year_raw"
            )
        )

        if year is None:

            matches = YEAR_RE.findall(
                combined
            )

            valid_years = [
                int(x)
                for x in matches
                if 2015 <= int(x) <= 2035
            ]

            if valid_years:
                year = valid_years[0]

        # ==============================================================
        # BATTERIA
        # ==============================================================

        battery = (
            self._extract_battery(
                combined
            )
        )

        # ==============================================================
        # POTENZA
        # ==============================================================

        power = (
            self._extract_power(
                combined
            )
        )

        # ==============================================================
        # INFOTAINMENT
        # ==============================================================

        (
            infotainment_candidate,
            infotainment_evidence,
        ) = self._extract_infotainment(
            combined
        )

        return {
            "listing_id": self._listing_id(
                item.get(
                    "url",
                    "",
                )
            ),
            "source": "autoscout24",
            "url": item.get(
                "url"
            ),
            "title": title,
            "price_eur": price,
            "mileage_km": mileage,
            "registration_year": year,
            "battery_kwh": battery,
            "power_hp": power,
            "description": description,
            "seller": seller,
            "collected_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "infotainment_129_candidate": (
                infotainment_candidate
            ),
            "classification_evidence": (
                infotainment_evidence
            ),
        }

    # ------------------------------------------------------------------
    # Prezzo
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_price(
        value,
    ):
        """
        Converte esclusivamente un valore proveniente da un campo
        strutturato di prezzo.

        NON effettua una ricerca generica del prezzo nell'HTML.
        """

        if value is None:
            return None

        if isinstance(
            value,
            (int, float),
        ):

            price = float(
                value
            )

        elif isinstance(
            value,
            dict,
        ):

            # Alcuni formati possono essere:
            # {"value": 28300}
            # {"amount": 28300}
            # {"price": 28300}

            nested = (
                value.get("value")
                or value.get("amount")
                or value.get("price")
            )

            if nested is None:
                return None

            return AutoScout24Scraper._extract_price(
                nested
            )

        else:

            text = str(
                value
            ).strip()

            text = (
                text
                .replace(
                    "€",
                    "",
                )
                .replace(
                    "\u00a0",
                    " ",
                )
                .strip()
            )

            # Formati:
            # 28.300
            # 28.300,00
            # 28300
            # 28300,00

            match = re.search(
                r"\d{1,3}(?:\.\d{3})+(?:,\d+)?"
                r"|\d+(?:,\d+)?",
                text,
            )

            if not match:
                return None

            number = match.group(0)

            if "." in number:
                number = number.replace(
                    ".",
                    "",
                )

            number = number.replace(
                ",",
                ".",
            )

            try:

                price = float(
                    number
                )

            except ValueError:
                return None

        # Controllo plausibilità.
        if price < 1000:
            return None

        if price > 200000:
            return None

        return price

    # ------------------------------------------------------------------
    # Chilometraggio
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_mileage(
        value,
    ):

        if value is None:
            return None

        if isinstance(
            value,
            dict,
        ):

            nested = (
                value.get("value")
                or value.get("amount")
                or value.get("mileage")
            )

            if nested is None:
                return None

            return AutoScout24Scraper._extract_mileage(
                nested
            )

        if isinstance(
            value,
            (int, float),
        ):

            return float(
                value
            )

        text = str(
            value
        ).strip()

        # Se il dato strutturato contiene "26173 km",
        # prendiamo solo il numero.
        match = re.search(
            r"\d[\d\.\s,]*",
            text,
        )

        if not match:
            return None

        return AutoScout24Scraper._parse_thousands_number(
            match.group(0)
        )

    @staticmethod
    def _parse_thousands_number(
        value,
    ):
        """
        Interpreta correttamente numeri italiani usati per il
        chilometraggio.

        Esempi:
            26.173 -> 26173
            40.698 -> 40698
            7.910  -> 7910
            7910   -> 7910
        """

        if value is None:
            return None

        text = str(
            value
        ).strip()

        text = (
            text.replace(
                "\u00a0",
                "",
            )
            .replace(
                " ",
                "",
            )
        )

        # Nel contesto del chilometraggio, un punto fra gruppi
        # di tre cifre è un separatore delle migliaia.
        if re.fullmatch(
            r"\d{1,3}(?:\.\d{3})+",
            text,
        ):

            text = text.replace(
                ".",
                "",
            )

        # Stessa cosa per la virgola, nel caso di formato
        # 26,173.
        elif re.fullmatch(
            r"\d{1,3}(?:,\d{3})+",
            text,
        ):

            text = text.replace(
                ",",
                "",
            )

        else:

            text = re.sub(
                r"[^\d]",
                "",
                text,
            )

        if not text:
            return None

        try:
            return float(
                text
            )

        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Batteria
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_battery(
        text: str,
    ):

        matches = BATTERY_RE.findall(
            text
        )

        if not matches:
            return None

        values = [
            float(x)
            for x in matches
        ]

        # Preferiamo valori tipici delle batterie ID.3.
        preferred = [
            x
            for x in values
            if x in {
                58,
                59,
                62,
                77,
                79,
            }
        ]

        if preferred:
            return preferred[0]

        return values[0]

    # ------------------------------------------------------------------
    # Potenza
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_power(
        text: str,
    ):

        matches = POWER_RE.findall(
            text
        )

        if not matches:
            return None

        for number, unit in matches:

            try:
                value = float(
                    number.replace(
                        ",",
                        ".",
                    )
                )

            except ValueError:
                continue

            unit_lower = unit.lower()

            if unit_lower == "cv":
                return value

            if unit_lower == "ps":
                return value

            if unit_lower == "kw":
                # Conversione approssimata kW -> CV.
                # 150 kW ≈ 204 CV.
                return round(
                    value * 1.35962
                )

        return None

    # ------------------------------------------------------------------
    # Anno
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_year(
        value,
    ):

        if value is None:
            return None

        if isinstance(
            value,
            dict,
        ):

            nested = (
                value.get("year")
                or value.get("value")
                or value.get("date")
            )

            if nested is None:
                return None

            return AutoScout24Scraper._extract_year(
                nested
            )

        text = str(
            value
        )

        match = re.search(
            r"\b(20\d{2})\b",
            text,
        )

        if not match:
            return None

        year = int(
            match.group(1)
        )

        if 2015 <= year <= 2035:
            return year

        return None

    # ------------------------------------------------------------------
    # Infotainment
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_infotainment(
        text: str,
    ):

        # Prima cerchiamo SEMPRE il 12,9".
        match_129 = (
            INFOTAINMENT_129_RE.search(
                text
            )
        )

        if match_129:

            evidence = (
                f"12,9\" trovato: "
                f"'{match_129.group(0)}'"
            )

            return (
                True,
                evidence,
            )

        # Se non c'è 12,9", cerchiamo il 12".
        match_12 = (
            INFOTAINMENT_12_RE.search(
                text
            )
        )

        if match_12:

            evidence = (
                f"12\" trovato: "
                f"'{match_12.group(0)}'"
            )

            return (
                False,
                evidence,
            )

        # Nessuna informazione sufficiente.
        return (
            None,
            "",
        )

    # ------------------------------------------------------------------
    # Conversione numerica generica
    # ------------------------------------------------------------------

    @staticmethod
    def _number(
        value,
    ):

        if value is None:
            return None

        if isinstance(
            value,
            (int, float),
        ):
            return float(
                value
            )

        if isinstance(
            value,
            dict,
        ):

            for key in (
                "value",
                "amount",
                "price",
            ):

                if key in value:

                    return (
                        AutoScout24Scraper._number(
                            value[key]
                        )
                    )

            return None

        s = str(
            value
        ).strip()

        s = (
            s.replace(
                "\u00a0",
                "",
            )
            .replace(
                " ",
                "",
            )
        )

        if (
            "." in s
            and "," in s
        ):

            s = s.replace(
                ".",
                "",
            )

            s = s.replace(
                ",",
                ".",
            )

        elif "," in s:

            s = s.replace(
                ",",
                ".",
            )

        elif s.count(".") > 1:

            s = s.replace(
                ".",
                "",
            )

        match = re.search(
            r"\d+(?:\.\d+)?",
            s,
        )

        if not match:
            return None

        try:

            return float(
                match.group()
            )

        except ValueError:
            return None

    # ------------------------------------------------------------------
    # ID annuncio
    # ------------------------------------------------------------------

    @staticmethod
    def _listing_id(
        url: str,
    ) -> str:

        return hashlib.sha256(
            url.encode(
                "utf-8"
            )
        ).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Deduplicazione
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate(
        items,
    ):

        unique = {}

        for item in items:

            listing_id = item.get(
                "listing_id"
            )

            if not listing_id:
                continue

            if (
                listing_id
                not in unique
            ):

                unique[
                    listing_id
                ] = item

                continue

            current = unique[
                listing_id
            ]

            current_score = sum(
                1
                for value
                in current.values()
                if value
                not in (
                    None,
                    "",
                )
            )

            new_score = sum(
                1
                for value
                in item.values()
                if value
                not in (
                    None,
                    "",
                )
            )

            if new_score > current_score:

                unique[
                    listing_id
                ] = item

        return list(
            unique.values()
        )
