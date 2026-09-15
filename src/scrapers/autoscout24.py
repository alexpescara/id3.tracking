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

KM_RE = re.compile(
    r"(\d[\d\.\s]*)\s*km\b",
    re.IGNORECASE,
)

YEAR_RE = re.compile(
    r"\b(20\d{2})\b",
)

BATTERY_RE = re.compile(
    r"\b(5[89]|6[0-9]|7[0-9]|8[0-9])\s*kWh\b",
    re.IGNORECASE,
)

POWER_RE = re.compile(
    r"\b(\d{2,3})\s*(?:CV|PS|kW)\b",
    re.IGNORECASE,
)

PRICE_RE = re.compile(
    r"(?:€\s*)?(\d{1,3}(?:[.\s]\d{3})+|\d{4,6})(?:\s*€)?",
)

INFOTAINMENT_RE = re.compile(
    r"""
    (
        12[\.,]?\s*9\s*(?:["”″]|pollici|inch)?
        |
        12[\.,]?\s*9
        |
        infotainment
        |
        discover\s+pro
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


class AutoScout24Scraper(BaseScraper):
    """
    Conservative public-page scraper for AutoScout24.

    The scraper:
    - uses the public search page;
    - extracts structured data when available;
    - does not bypass CAPTCHA, login, robots restrictions or anti-bot
      mechanisms;
    - does not use paid APIs, proxies or external scraping services.
    """

    def search(self, search_url: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        s_cfg = self.config["scraper"]

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=s_cfg.get("headless", True)
            )

            context = browser.new_context(
                user_agent=s_cfg.get("user_agent"),
                locale="it-IT",
                viewport={"width": 1440, "height": 1000},
            )

            page = context.new_page()
            page.set_default_timeout(
                s_cfg.get("timeout_ms", 30000)
            )

            try:
                print(f"[AutoScout24] Apertura: {search_url}")

                page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                )

                page.wait_for_timeout(2500)

                self._dismiss_common_consent(page)

                max_pages = int(
                    s_cfg.get("max_pages", 1)
                )

                for page_no in range(max_pages):
                    print(
                        f"[AutoScout24] Elaborazione pagina "
                        f"{page_no + 1}/{max_pages}"
                    )

                    html = page.content()

                    page_results = self._parse_search_page(
                        html,
                        page.url,
                    )

                    print(
                        f"[AutoScout24] Annunci trovati nella pagina: "
                        f"{len(page_results)}"
                    )

                    results.extend(page_results)

                    if page_no + 1 >= max_pages:
                        break

                    next_link = page.locator(
                        'a[aria-label*="pagina successiva" i], '
                        'a[aria-label*="next" i], '
                        'a[title*="successiva" i]'
                    )

                    if next_link.count() == 0:
                        break

                    href = next_link.first.get_attribute("href")

                    if not href:
                        break

                    next_url = urljoin(page.url, href)

                    time.sleep(
                        float(
                            s_cfg.get(
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

        results = self._deduplicate(results)

        print(
            f"[AutoScout24] Totale annunci unici: {len(results)}"
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
                locator = page.locator(selector)

                if locator.count():
                    locator.first.click(timeout=1500)
                    page.wait_for_timeout(500)
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

        soup = BeautifulSoup(html, "lxml")

        cards: list[dict[str, Any]] = []

        # --------------------------------------------------------------
        # 1. __NEXT_DATA__
        #
        # AutoScout24 utilizza dati strutturati lato client. Cerchiamo
        # ricorsivamente gli oggetti che sembrano rappresentare annunci.
        # --------------------------------------------------------------

        next_data = self._extract_next_data(soup)

        if next_data is not None:
            next_candidates = self._find_listing_objects(
                next_data
            )

            for obj in next_candidates:
                parsed = self._from_structured_object(
                    obj,
                    source_url,
                )

                if parsed.get("url"):
                    cards.append(parsed)

        # --------------------------------------------------------------
        # 2. JSON-LD
        # --------------------------------------------------------------

        jsonld_cards = []

        for script in soup.find_all(
            "script",
            type="application/ld+json",
        ):
            raw_script = script.string or script.get_text()

            if not raw_script.strip():
                continue

            try:
                data = json.loads(raw_script)

            except Exception:
                continue

            candidates = (
                data
                if isinstance(data, list)
                else [data]
            )

            for obj in candidates:

                if not isinstance(obj, dict):
                    continue

                obj_type = obj.get("@type")

                if isinstance(obj_type, list):
                    valid_type = any(
                        x in {
                            "Car",
                            "Vehicle",
                            "Product",
                        }
                        for x in obj_type
                    )
                else:
                    valid_type = obj_type in {
                        "Car",
                        "Vehicle",
                        "Product",
                    }

                if valid_type:
                    parsed = self._from_jsonld(
                        obj,
                        source_url,
                    )

                    if parsed.get("url"):
                        jsonld_cards.append(parsed)

        # JSON-LD viene usato se non abbiamo già trovato gli stessi
        # annunci tramite __NEXT_DATA__.
        cards.extend(jsonld_cards)

        # --------------------------------------------------------------
        # 3. Fallback HTML
        # --------------------------------------------------------------

        if not cards:

            for a in soup.find_all(
                "a",
                href=True,
            ):
                href = a.get("href", "")
                text = " ".join(
                    a.stripped_strings
                )

                if "/annunci/" not in href:
                    continue

                if "id.3" not in text.lower():
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
    def _extract_next_data(soup: BeautifulSoup):
        script = soup.find(
            "script",
            id="__NEXT_DATA__",
        )

        if script is None:
            return None

        raw = script.string or script.get_text()

        if not raw.strip():
            return None

        try:
            return json.loads(raw)

        except Exception:
            return None

    def _find_listing_objects(
        self,
        data: Any,
    ) -> list[dict[str, Any]]:
        """
        Cerca ricorsivamente oggetti che sembrano rappresentare
        annunci AutoScout24.

        Non assumiamo una struttura rigida di __NEXT_DATA__ perché può
        cambiare nel tempo.
        """

        found: list[dict[str, Any]] = []

        def walk(value: Any):

            if isinstance(value, dict):

                if self._looks_like_listing(value):
                    found.append(value)

                for child in value.values():
                    walk(child)

            elif isinstance(value, list):

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

        has_url = (
            "url" in keys_lower
            or "detailurl" in keys_lower
            or "href" in keys_lower
            or "deeplink" in keys_lower
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
    # Conversione dati strutturati
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

        if isinstance(url, dict):
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
                "title": title or "Volkswagen ID.3",
                "description": description or "",
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
        """
        Cerca una chiave senza assumere il casing esatto.
        """

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

        if isinstance(seller, dict):
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

        offers = obj.get("offers") or {}

        if isinstance(offers, list):
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

        seller = self._extract_jsonld_seller(
            obj
        )

        price = None

        if isinstance(offers, dict):
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
                "mileage_raw": self._jsonld_mileage(
                    obj
                ),
                "year_raw": self._jsonld_year(
                    obj
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

        seller = obj.get("seller")

        if isinstance(seller, dict):
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

        if isinstance(mileage, dict):
            return mileage.get("value")

        return mileage

    @staticmethod
    def _jsonld_year(
        obj: dict,
    ):

        return (
            obj.get("vehicleModelDate")
            or obj.get("productionDate")
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
                # IMPORTANT:
                # Non cerchiamo più il prezzo genericamente nel testo.
                # Questo evita falsi prezzi come 8264, 4791, ecc.
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

        title = item.get(
            "title",
            "",
        ) or ""

        description = item.get(
            "description",
            "",
        ) or ""

        seller = item.get(
            "seller"
        )

        combined = (
            f"{title} "
            f"{description} "
            f"{raw}"
        )

        # --------------------------------------------------------------
        # PREZZO
        #
        # Priorità assoluta al dato strutturato.
        #
        # NON utilizziamo più un regex generico sul blocco completo,
        # perché era la causa dei falsi prezzi.
        # --------------------------------------------------------------

        price = self._extract_price(
            item.get("price_raw")
        )

        # --------------------------------------------------------------
        # KM
        # --------------------------------------------------------------

        mileage = self._number(
            item.get("mileage_raw")
        )

        if mileage is None:

            match = KM_RE.search(
                combined
            )

            if match:
                mileage = self._number(
                    match.group(1)
                )

        # --------------------------------------------------------------
        # ANNO
        # --------------------------------------------------------------

        year = self._number(
            item.get("year_raw")
        )

        if year is not None:
            year = int(year)

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

        # --------------------------------------------------------------
        # BATTERIA
        # --------------------------------------------------------------

        battery = None

        match = BATTERY_RE.search(
            combined
        )

        if match:
            battery = float(
                match.group(1)
            )

        # --------------------------------------------------------------
        # POTENZA
        # --------------------------------------------------------------

        power = None

        match = POWER_RE.search(
            combined
        )

        if match:

            value = int(
                match.group(1)
            )

            # Evitiamo di interpretare valori in kW come CV.
            unit = match.group(0).lower()

            if "kw" not in unit:
                power = value

        # --------------------------------------------------------------
        # INFOTAINMENT 12.9"
        # --------------------------------------------------------------

        infotainment_match = (
            INFOTAINMENT_RE.search(
                combined
            )
        )

        infotainment_candidate = (
            infotainment_match is not None
        )

        classification_evidence = ""

        if infotainment_match:
            classification_evidence = (
                "Possibile infotainment 12,9\": "
                f"'{infotainment_match.group(1)}'"
            )

        return {
            "listing_id": self._listing_id(
                item.get("url", "")
            ),
            "source": "autoscout24",
            "url": item.get("url"),
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
                classification_evidence
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
        Converte SOLO un valore che proviene da un campo strutturato
        di prezzo.

        Non cerca il prezzo casualmente nell'intero HTML.
        """

        if value is None:
            return None

        # Caso numerico
        if isinstance(
            value,
            (int, float),
        ):
            price = float(value)

        # Caso stringa
        else:

            text = str(value).strip()

            # Rimuove simbolo euro e spazi.
            text = (
                text
                .replace("€", "")
                .replace("\u00a0", " ")
                .strip()
            )

            # Formato italiano:
            # 24.900
            # 24.900,00
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
                price = float(number)

            except ValueError:
                return None

        # --------------------------------------------------------------
        # Controllo di plausibilità.
        #
        # Non vogliamo salvare come prezzo valori palesemente
        # incompatibili con un'automobile.
        # --------------------------------------------------------------

        if price < 1000:
            return None

        if price > 200000:
            return None

        return price

    # ------------------------------------------------------------------
    # Conversione numerica
    # ------------------------------------------------------------------

    @staticmethod
    def _number(value):

        if value is None:
            return None

        if isinstance(
            value,
            (int, float),
        ):
            return float(value)

        # Gestione di dizionari come:
        # {"value": 24900}
        # {"amount": 24900}
        # {"price": 24900}

        if isinstance(value, dict):

            for key in (
                "value",
                "amount",
                "price",
            ):

                if key in value:
                    return AutoScout24Scraper._number(
                        value[key]
                    )

            return None

        s = str(value).strip()

        # Migliaia italiane:
        # 15.189 -> 15189
        #
        # Decimali:
        # 15189,5 -> 15189.5

        s = (
            s.replace(
                "\u00a0",
                " ",
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

        # Se ci sono più punti, probabilmente sono separatori
        # delle migliaia.
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
            url.encode("utf-8")
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

            # Se abbiamo trovato lo stesso annuncio più volte,
            # preferiamo quello con più informazioni.
            if listing_id not in unique:
                unique[listing_id] = item
                continue

            current = unique[listing_id]

            current_score = (
                sum(
                    1
                    for value in current.values()
                    if value not in (
                        None,
                        "",
                    )
                )
            )

            new_score = (
                sum(
                    1
                    for value in item.values()
                    if value not in (
                        None,
                        "",
                    )
                )
            )

            if new_score > current_score:
                unique[listing_id] = item

        return list(
            unique.values()
        )
