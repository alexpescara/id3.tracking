from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


class AutoScout24Scraper:
    BASE_URL = "https://www.autoscout24.it"

    def __init__(self, config: dict):
        self.config = config
        self.scraper_cfg = config.get("scraper", {})

        self.headless = self.scraper_cfg.get("headless", True)
        self.timeout_ms = int(self.scraper_cfg.get("timeout_ms", 30000))
        self.delay_seconds = float(self.scraper_cfg.get("delay_seconds", 2.5))
        self.max_pages = int(self.scraper_cfg.get("max_pages", 5))

        # Numero massimo di singole schede da aprire.
        # Evita di fare troppe richieste in una singola esecuzione.
        self.max_detail_pages = int(
            self.scraper_cfg.get("max_detail_pages", 30)
        )

        self.user_agent = self.scraper_cfg.get(
            "user_agent",
            "ID3-Market-Monitor/0.1 (open-source research project)",
        )

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def search(self, search_url: str) -> list[dict[str, Any]]:
        """
        1. Apre le pagine dei risultati AutoScout24.
        2. Raccoglie gli URL delle singole inserzioni.
        3. Apre le singole inserzioni.
        4. Estrae i dati tecnici/equipaggiamento.
        """

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)

            context = browser.new_context(
                user_agent=self.user_agent,
                locale="it-IT",
                timezone_id="Europe/Rome",
                viewport={"width": 1440, "height": 1000},
            )

            page = context.new_page()
            page.set_default_timeout(self.timeout_ms)

            try:
                listing_urls = self._collect_listing_urls(
                    page,
                    search_url,
                )

                print(
                    f"URL annunci individuati: {len(listing_urls)}"
                )

                if not listing_urls:
                    return []

                results: list[dict[str, Any]] = []

                for index, url in enumerate(
                    listing_urls[: self.max_detail_pages],
                    start=1,
                ):
                    print(
                        f"[{index}/{min(len(listing_urls), self.max_detail_pages)}] "
                        f"Apro dettaglio: {url}"
                    )

                    try:
                        listing = self._scrape_detail_page(
                            page,
                            url,
                        )

                        if listing:
                            results.append(listing)

                    except Exception as exc:
                        print(
                            f"ERRORE dettaglio {url}: "
                            f"{type(exc).__name__}: {exc}"
                        )

                    # Ritardo prudenziale tra le singole schede.
                    if index < min(
                        len(listing_urls),
                        self.max_detail_pages,
                    ):
                        time.sleep(self.delay_seconds)

                return results

            finally:
                context.close()
                browser.close()

    # ------------------------------------------------------------------
    # SEARCH RESULTS
    # ------------------------------------------------------------------

    def _collect_listing_urls(
        self,
        page,
        search_url: str,
    ) -> list[str]:

        urls: list[str] = []
        seen: set[str] = set()

        current_url = search_url

        for page_number in range(1, self.max_pages + 1):
            print(
                f"Pagina risultati AutoScout24 "
                f"{page_number}/{self.max_pages}"
            )

            try:
                page.goto(
                    current_url,
                    wait_until="domcontentloaded",
                    timeout=self.timeout_ms,
                )
            except Exception as exc:
                print(
                    f"Errore apertura pagina risultati: "
                    f"{type(exc).__name__}: {exc}"
                )
                break

            self._wait_for_results(page)

            # Primo metodo: link HTML visibili.
            page_urls = self._extract_listing_urls_from_html(
                page
            )

            # Secondo metodo: JSON/Next.js incorporato nella pagina.
            if not page_urls:
                page_urls = self._extract_listing_urls_from_json(
                    page
                )

            for url in page_urls:
                normalized = self._normalize_listing_url(url)

                if normalized and normalized not in seen:
                    seen.add(normalized)
                    urls.append(normalized)

            print(
                f"  Trovati {len(page_urls)} URL nella pagina"
            )

            next_url = self._find_next_page_url(page)

            if not next_url:
                break

            if next_url in seen:
                break

            current_url = next_url

            time.sleep(self.delay_seconds)

        return urls

    def _wait_for_results(self, page) -> None:
        """
        Attende che la pagina abbia effettivamente caricato
        almeno parte degli annunci.
        """

        try:
            page.wait_for_selector(
                'a[href*="/offerta/"]',
                timeout=10000,
            )
            return
        except Exception:
            pass

        try:
            page.wait_for_timeout(3000)
        except Exception:
            pass

    def _extract_listing_urls_from_html(
        self,
        page,
    ) -> list[str]:

        urls: list[str] = []

        try:
            links = page.locator("a").evaluate_all(
                """
                els => els.map(a => ({
                    href: a.href,
                    text: (a.innerText || "").trim()
                }))
                """
            )
        except Exception:
            return urls

        for item in links:
            href = item.get("href")

            if not href:
                continue

            if self._looks_like_listing_url(href):
                urls.append(href)

        return urls

    def _extract_listing_urls_from_json(
        self,
        page,
    ) -> list[str]:

        urls: list[str] = []

        try:
            html = page.content()
        except Exception:
            return urls

        soup = BeautifulSoup(html, "lxml")

        for script in soup.find_all("script"):
            text = script.string or script.get_text()

            if not text:
                continue

            # Cerca URL AutoScout24 contenenti /offerta/
            matches = re.findall(
                r'https?://www\.autoscout24\.it/offerta/[^"\'\\\s]+',
                text,
            )

            for match in matches:
                urls.append(match)

        return urls

    def _find_next_page_url(self, page) -> str | None:
        """
        Cerca il link alla pagina successiva.
        """

        selectors = [
            'a[aria-label*="successiva" i]',
            'a[title*="successiva" i]',
            'a[href*="page="]',
        ]

        for selector in selectors:
            try:
                elements = page.locator(selector)

                count = elements.count()

                for i in range(count):
                    href = elements.nth(i).get_attribute("href")

                    if href and self._looks_like_search_page_url(
                        href
                    ):
                        return urljoin(
                            self.BASE_URL,
                            href,
                        )

            except Exception:
                continue

        return None

    # ------------------------------------------------------------------
    # DETAIL PAGE
    # ------------------------------------------------------------------

    def _scrape_detail_page(
        self,
        page,
        url: str,
    ) -> dict[str, Any] | None:

        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
        except Exception as exc:
            print(
                f"  Impossibile aprire dettaglio: {exc}"
            )
            return None

        # Alcuni dati vengono caricati dopo il DOM iniziale.
        try:
            page.wait_for_timeout(2500)
        except Exception:
            pass

        html = page.content()
        soup = BeautifulSoup(html, "lxml")

        jsonld_objects = self._extract_jsonld_objects(soup)
        next_data = self._extract_next_data(soup)

        visible_text = self._get_visible_text(soup)

        title = self._extract_title(
            soup,
            jsonld_objects,
            next_data,
        )

        price = self._extract_price(
            soup,
            jsonld_objects,
            next_data,
            visible_text,
        )

        mileage = self._extract_mileage(
            soup,
            jsonld_objects,
            next_data,
            visible_text,
        )

        registration_year = self._extract_registration_year(
            soup,
            jsonld_objects,
            next_data,
            visible_text,
        )

        battery_kwh = self._extract_battery(
            title,
            visible_text,
            jsonld_objects,
            next_data,
        )

        power_hp = self._extract_power(
            title,
            visible_text,
            jsonld_objects,
            next_data,
        )

        description = self._extract_description(
            soup,
            jsonld_objects,
            next_data,
        )

        seller = self._extract_seller(
            soup,
            jsonld_objects,
            next_data,
        )

        equipment = self._extract_equipment(
            soup,
            visible_text,
        )

        infotainment_candidate, classification_evidence = (
            self._detect_129_infotainment(
                title=title,
                description=description,
                equipment=equipment,
                visible_text=visible_text,
            )
        )

        listing_id = self._make_listing_id(url)

        return {
            "listing_id": listing_id,
            "source": "autoscout24",
            "url": url,
            "title": title,
            "price_eur": price,
            "mileage_km": mileage,
            "registration_year": registration_year,
            "battery_kwh": battery_kwh,
            "power_hp": power_hp,
            "description": description,
            "seller": seller,
            "equipment": equipment,
            "collected_at": datetime.now().isoformat(
                timespec="seconds"
            ),
            "infotainment_129_candidate": infotainment_candidate,
            "classification_evidence": classification_evidence,
        }

    # ------------------------------------------------------------------
    # JSON-LD / NEXT DATA
    # ------------------------------------------------------------------

    def _extract_jsonld_objects(
        self,
        soup: BeautifulSoup,
    ) -> list[Any]:

        objects: list[Any] = []

        for script in soup.find_all(
            "script",
            attrs={"type": "application/ld+json"},
        ):
            raw = script.string or script.get_text()

            if not raw:
                continue

            raw = raw.strip()

            try:
                parsed = json.loads(raw)

                if isinstance(parsed, list):
                    objects.extend(parsed)
                else:
                    objects.append(parsed)

            except Exception:
                continue

        return objects

    def _extract_next_data(
        self,
        soup: BeautifulSoup,
    ) -> Any | None:

        script = soup.find(
            "script",
            id="__NEXT_DATA__",
        )

        if not script:
            return None

        raw = script.string or script.get_text()

        if not raw:
            return None

        try:
            return json.loads(raw)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # GENERIC DATA SEARCH
    # ------------------------------------------------------------------

    def _walk_values(
        self,
        obj: Any,
        key_names: set[str] | None = None,
    ):
        """
        Attraversa ricorsivamente dizionari/liste.

        Restituisce coppie:
            key, value
        """

        if isinstance(obj, dict):
            for key, value in obj.items():

                if key_names is None or key.lower() in key_names:
                    yield key, value

                yield from self._walk_values(
                    value,
                    key_names,
                )

        elif isinstance(obj, list):
            for item in obj:
                yield from self._walk_values(
                    item,
                    key_names,
                )

    def _find_values_by_keys(
        self,
        objects: list[Any],
        keys: set[str],
    ) -> list[Any]:

        values: list[Any] = []

        normalized = {
            x.lower()
            for x in keys
        }

        for obj in objects:
            for _, value in self._walk_values(
                obj,
                normalized,
            ):
                values.append(value)

        return values

    # ------------------------------------------------------------------
    # PRICE
    # ------------------------------------------------------------------

    def _extract_price(
        self,
        soup: BeautifulSoup,
        jsonld_objects: list[Any],
        next_data: Any,
        visible_text: str,
    ) -> float | None:

        # 1. JSON-LD Offer.price
        for obj in jsonld_objects:

            if not isinstance(obj, dict):
                continue

            offers = obj.get("offers")

            if isinstance(offers, dict):
                value = self._numeric_price(
                    offers.get("price")
                )

                if value:
                    return value

            elif isinstance(offers, list):
                for offer in offers:
                    if isinstance(offer, dict):
                        value = self._numeric_price(
                            offer.get("price")
                        )

                        if value:
                            return value

        # 2. NEXT_DATA / dati strutturati
        if next_data is not None:
            candidates = self._find_values_by_keys(
                [next_data],
                {
                    "price",
                    "pricevalue",
                    "listingprice",
                    "vehicleprice",
                },
            )

            for candidate in candidates:
                value = self._numeric_price(candidate)

                if value:
                    # Evitiamo numeri palesemente non plausibili.
                    if 3000 <= value <= 200000:
                        return value

        # 3. HTML, ma solo in contesti espliciti di prezzo.
        patterns = [
            r'€\s*([0-9][0-9\.\s]*)',
            r'([0-9][0-9\.\s]*)\s*€',
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                visible_text,
                flags=re.IGNORECASE,
            )

            if match:
                value = self._parse_european_number(
                    match.group(1)
                )

                if value and 3000 <= value <= 200000:
                    return value

        return None

    def _numeric_price(
        self,
        value: Any,
    ) -> float | None:

        if value is None:
            return None

        if isinstance(value, (int, float)):
            number = float(value)

            if number <= 0:
                return None

            return number

        if isinstance(value, str):
            text = value.strip()

            # Evita di interpretare stringhe non monetarie.
            if not re.search(r"\d", text):
                return None

            match = re.search(
                r"\d[\d\.\s,]*",
                text,
            )

            if not match:
                return None

            return self._parse_european_number(
                match.group(0)
            )

        return None

    # ------------------------------------------------------------------
    # MILEAGE
    # ------------------------------------------------------------------

    def _extract_mileage(
        self,
        soup: BeautifulSoup,
        jsonld_objects: list[Any],
        next_data: Any,
        visible_text: str,
    ) -> int | None:

        # JSON-LD
        for obj in jsonld_objects:

            if not isinstance(obj, dict):
                continue

            mileage = obj.get("mileageFromOdometer")

            if isinstance(mileage, dict):
                value = mileage.get("value")

                parsed = self._parse_integer(value)

                if parsed is not None:
                    return parsed

        # NEXT_DATA
        if next_data is not None:
            candidates = self._find_values_by_keys(
                [next_data],
                {
                    "mileage",
                    "mileagekm",
                    "kilometers",
                    "kilometres",
                    "odometer",
                },
            )

            for candidate in candidates:
                parsed = self._parse_mileage(candidate)

                if parsed is not None:
                    return parsed

        # Testo visibile.
        patterns = [
            r'(\d[\d\.\s]*)\s*km\b',
            r'(\d[\d\.\s]*)\s*chilometri\b',
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                visible_text,
                flags=re.IGNORECASE,
            )

            if match:
                parsed = self._parse_integer(
                    match.group(1)
                )

                if parsed is not None:
                    return parsed

        return None

    def _parse_mileage(
        self,
        value: Any,
    ) -> int | None:

        if value is None:
            return None

        if isinstance(value, (int, float)):
            number = int(value)

            if 0 <= number <= 1000000:
                return number

            return None

        if isinstance(value, str):
            match = re.search(
                r'\d[\d\.\s]*',
                value,
            )

            if match:
                return self._parse_integer(
                    match.group(0)
                )

        return None

    # ------------------------------------------------------------------
    # YEAR
    # ------------------------------------------------------------------

    def _extract_registration_year(
        self,
        soup: BeautifulSoup,
        jsonld_objects: list[Any],
        next_data: Any,
        visible_text: str,
    ) -> int | None:

        # JSON-LD date
        for obj in jsonld_objects:

            if not isinstance(obj, dict):
                continue

            date_fields = [
                obj.get("datePosted"),
                obj.get("dateVehicleFirstRegistered"),
                obj.get("vehicleConfiguration"),
            ]

            for value in date_fields:
                year = self._extract_year_from_value(value)

                if year:
                    return year

        # NEXT_DATA
        if next_data is not None:
            candidates = self._find_values_by_keys(
                [next_data],
                {
                    "registrationdate",
                    "firstregistration",
                    "datefirstregistered",
                    "registrationyear",
                    "year",
                },
            )

            for candidate in candidates:
                year = self._extract_year_from_value(
                    candidate
                )

                if year and 2000 <= year <= 2035:
                    return year

        # Testo.
        patterns = [
            r'\b(20[0-3]\d)\b',
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                visible_text,
            )

            if match:
                year = int(match.group(1))

                if 2000 <= year <= 2035:
                    return year

        return None

    def _extract_year_from_value(
        self,
        value: Any,
    ) -> int | None:

        if value is None:
            return None

        text = str(value)

        match = re.search(
            r'\b(20[0-3]\d)\b',
            text,
        )

        if not match:
            return None

        return int(match.group(1))

    # ------------------------------------------------------------------
    # BATTERY
    # ------------------------------------------------------------------

    def _extract_battery(
        self,
        title: str,
        visible_text: str,
        jsonld_objects: list[Any],
        next_data: Any,
    ) -> float | None:

        # Prima il titolo: spesso contiene "58 kWh", "59 kWh",
        # "77 kWh", ecc.
        battery = self._parse_battery_from_text(title)

        if battery is not None:
            return battery

        # Poi dati strutturati.
        objects = list(jsonld_objects)

        if next_data is not None:
            objects.append(next_data)

        candidates = self._find_values_by_keys(
            objects,
            {
                "batterycapacity",
                "batterycapacitykwh",
                "battery_kwh",
                "battery",
                "capacity",
            },
        )

        for candidate in candidates:
            battery = self._parse_battery_value(candidate)

            if battery is not None:
                return battery

        # Infine testo completo.
        return self._parse_battery_from_text(
            visible_text
        )

    def _parse_battery_from_text(
        self,
        text: str,
    ) -> float | None:

        patterns = [
            r'\b(\d{2,3}(?:[.,]\d+)?)\s*kwh\b',
            r'\b(\d{2,3}(?:[.,]\d+)?)\s*kwh\s*\(net',
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:
                value = float(
                    match.group(1).replace(",", ".")
                )

                if 30 <= value <= 150:
                    return value

        return None

    def _parse_battery_value(
        self,
        value: Any,
    ) -> float | None:

        if isinstance(value, dict):
            for key in (
                "value",
                "capacity",
                "kwh",
                "batteryCapacity",
            ):
                if key in value:
                    result = self._parse_battery_value(
                        value[key]
                    )

                    if result is not None:
                        return result

            return None

        if isinstance(value, (int, float)):
            number = float(value)

            if 30 <= number <= 150:
                return number

            # Eventuale valore in Wh.
            if 30000 <= number <= 150000:
                return round(number / 1000, 1)

            return None

        if isinstance(value, str):
            return self._parse_battery_from_text(value)

        return None

    # ------------------------------------------------------------------
    # POWER
    # ------------------------------------------------------------------

    def _extract_power(
        self,
        title: str,
        visible_text: str,
        jsonld_objects: list[Any],
        next_data: Any,
    ) -> int | None:

        # 1. Il titolo è molto più affidabile del generico
        # campo potenza mostrato dalla lista AutoScout24.
        hp = self._parse_hp_from_text(title)

        if hp is not None:
            return hp

        # 2. kW nel titolo.
        kw = self._parse_kw_from_text(title)

        if kw is not None:
            return self._kw_to_hp(kw)

        # 3. JSON-LD.
        objects = list(jsonld_objects)

        if next_data is not None:
            objects.append(next_data)

        candidates = self._find_values_by_keys(
            objects,
            {
                "power",
                "powerkw",
                "enginepower",
                "maxpower",
                "maximumPower",
            },
        )

        for candidate in candidates:
            hp = self._parse_power_value(candidate)

            if hp is not None:
                return hp

        # 4. Testo completo, ma solo cercando espressioni
        # esplicite di potenza.
        hp = self._parse_hp_from_text(
            visible_text
        )

        if hp is not None:
            return hp

        kw = self._parse_kw_from_text(
            visible_text
        )

        if kw is not None:
            return self._kw_to_hp(kw)

        return None

    def _parse_hp_from_text(
        self,
        text: str,
    ) -> int | None:

        patterns = [
            r'(\d{2,3})\s*(?:cv|CV)\b',
            r'(\d{2,3})\s*(?:cavalli)\b',
        ]

        for pattern in patterns:
            matches = re.findall(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            for match in matches:
                hp = int(match)

                if 50 <= hp <= 500:
                    return hp

        return None

    def _parse_kw_from_text(
        self,
        text: str,
    ) -> float | None:

        matches = re.findall(
            r'(\d{2,3}(?:[.,]\d+)?)\s*kW\b',
            text,
            flags=re.IGNORECASE,
        )

        for match in matches:
            kw = float(
                match.replace(",", ".")
            )

            if 30 <= kw <= 400:
                return kw

        return None

    def _kw_to_hp(
        self,
        kw: float,
    ) -> int:

        # 1 kW = 1.35962 CV
        return round(kw * 1.35962)

    def _parse_power_value(
        self,
        value: Any,
    ) -> int | None:

        if isinstance(value, dict):

            for key in (
                "horsepower",
                "hp",
                "cv",
            ):
                if key in value:
                    hp = self._parse_hp_from_text(
                        str(value[key])
                    )

                    if hp is not None:
                        return hp

            for key in (
                "kw",
                "kW",
                "powerKw",
            ):
                if key in value:
                    try:
                        kw = float(value[key])
                        return self._kw_to_hp(kw)
                    except Exception:
                        pass

            for child in value.values():
                result = self._parse_power_value(
                    child
                )

                if result is not None:
                    return result

            return None

        if isinstance(value, (int, float)):
            number = float(value)

            # Qui assumiamo kW per valori realistici
            # dell'ID.3.
            if 30 <= number <= 400:
                return self._kw_to_hp(number)

            return None

        if isinstance(value, str):
            hp = self._parse_hp_from_text(value)

            if hp is not None:
                return hp

            kw = self._parse_kw_from_text(value)

            if kw is not None:
                return self._kw_to_hp(kw)

        return None

    # ------------------------------------------------------------------
    # DESCRIPTION
    # ------------------------------------------------------------------

    def _extract_description(
        self,
        soup: BeautifulSoup,
        jsonld_objects: list[Any],
        next_data: Any,
    ) -> str:

        for obj in jsonld_objects:

            if not isinstance(obj, dict):
                continue

            value = obj.get("description")

            if isinstance(value, str):
                value = self._clean_text(value)

                if len(value) > 20:
                    return value

        # Cerca elementi tipici della descrizione.
        selectors = [
            '[data-testid*="description" i]',
            '[class*="description" i]',
        ]

        for selector in selectors:
            try:
                element = soup.select_one(selector)

                if element:
                    text = self._clean_text(
                        element.get_text(" ", strip=True)
                    )

                    if len(text) > 20:
                        return text

            except Exception:
                continue

        return ""

    # ------------------------------------------------------------------
    # SELLER
    # ------------------------------------------------------------------

    def _extract_seller(
        self,
        soup: BeautifulSoup,
        jsonld_objects: list[Any],
        next_data: Any,
    ) -> str:

        for obj in jsonld_objects:

            if not isinstance(obj, dict):
                continue

            seller = obj.get("seller")

            if isinstance(seller, dict):
                name = seller.get("name")

                if isinstance(name, str):
                    name = self._clean_text(name)

                    if name:
                        return name

        selectors = [
            '[data-testid*="seller" i]',
            '[data-testid*="dealer" i]',
            '[class*="seller" i]',
            '[class*="dealer" i]',
        ]

        for selector in selectors:
            try:
                element = soup.select_one(selector)

                if element:
                    text = self._clean_text(
                        element.get_text(" ", strip=True)
                    )

                    if text:
                        return text

            except Exception:
                continue

        return ""

    # ------------------------------------------------------------------
    # EQUIPMENT
    # ------------------------------------------------------------------

    def _extract_equipment(
        self,
        soup: BeautifulSoup,
        visible_text: str,
    ) -> str:

        pieces: list[str] = []

        selectors = [
            '[data-testid*="equipment" i]',
            '[data-testid*="equip" i]',
            '[class*="equipment" i]',
            '[class*="equip" i]',
        ]

        for selector in selectors:
            try:
                elements = soup.select(selector)

                for element in elements:
                    text = self._clean_text(
                        element.get_text(" ", strip=True)
                    )

                    if text and text not in pieces:
                        pieces.append(text)

            except Exception:
                continue

        if pieces:
            return " | ".join(pieces)

        # Fallback: restituiamo solo le righe del testo che
        # sembrano riferirsi all'equipaggiamento.
        equipment_keywords = [
            "radio",
            "display",
            "touchscreen",
            "schermo",
            "navigazione",
            "adaptive cruise",
            "climatizzatore",
            "telecamera",
            "sedili riscaldati",
            "carica",
            "park assist",
            "fari",
            "led",
        ]

        lines = []

        for line in visible_text.splitlines():
            normalized = line.lower()

            if any(
                keyword in normalized
                for keyword in equipment_keywords
            ):
                clean = self._clean_text(line)

                if clean:
                    lines.append(clean)

        return " | ".join(
            dict.fromkeys(lines)
        )

    # ------------------------------------------------------------------
    # INFOTAINMENT 12.9"
    # ------------------------------------------------------------------

    def _detect_129_infotainment(
        self,
        title: str,
        description: str,
        equipment: str,
        visible_text: str,
    ) -> tuple[bool | None, str]:

        combined = " ".join(
            [
                title,
                description,
                equipment,
                visible_text,
            ]
        )

        # Normalizzazione minima.
        normalized = combined.replace(
            "″",
            '"',
        ).replace(
            "”",
            '"',
        ).replace(
            "’",
            "'",
        )

        # Prima cerchiamo esplicitamente 12.9".
        patterns_129 = [
            r'\b12[.,]9\s*(?:["″]|pollici|inch)',
            r'\b12[.,]9\s*["″]',
            r'\b12[.,]9\s*pollici',
            r'\b12[.,]9\s*inch',
            r'\b12[.,]9\s*\'\'',
            r'32[.,]8\s*cm\s*\(\s*12[.,]9',
        ]

        for pattern in patterns_129:
            match = re.search(
                pattern,
                normalized,
                flags=re.IGNORECASE,
            )

            if match:
                snippet = self._extract_evidence_snippet(
                    normalized,
                    match.start(),
                    match.end(),
                )

                return True, snippet

        # Poi cerchiamo esplicitamente 12".
        # Attenzione: non basta trovare "12", deve essere
        # associato a display/schermo/touchscreen.
        patterns_12 = [
            r'\b12\s*(?:["″]|pollici|inch)',
            r'\b12\s*["″]',
            r'\b12\s*pollici',
            r'\b12\s*inch',
            r'30[.,]5\s*cm\s*\(\s*12',
        ]

        for pattern in patterns_12:
            match = re.search(
                pattern,
                normalized,
                flags=re.IGNORECASE,
            )

            if match:

                start = max(
                    0,
                    match.start() - 100,
                )

                end = min(
                    len(normalized),
                    match.end() + 100,
                )

                context = normalized[
                    start:end
                ].lower()

                infotainment_words = [
                    "display",
                    "schermo",
                    "touchscreen",
                    "touch screen",
                    "radio",
                    "ready 2 discover",
                    "ready2discover",
                ]

                if any(
                    word in context
                    for word in infotainment_words
                ):
                    snippet = self._extract_evidence_snippet(
                        normalized,
                        match.start(),
                        match.end(),
                    )

                    return False, snippet

        # Nessuna informazione sufficientemente esplicita.
        return None, ""

    def _extract_evidence_snippet(
        self,
        text: str,
        start: int,
        end: int,
    ) -> str:

        left = max(
            0,
            start - 100,
        )

        right = min(
            len(text),
            end + 150,
        )

        snippet = text[left:right]

        return self._clean_text(snippet)

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    def _extract_title(
        self,
        soup: BeautifulSoup,
        jsonld_objects: list[Any],
        next_data: Any,
    ) -> str:

        # JSON-LD
        for obj in jsonld_objects:

            if not isinstance(obj, dict):
                continue

            name = obj.get("name")

            if isinstance(name, str):
                name = self._clean_text(name)

                if name:
                    return name

        # <h1>
        h1 = soup.find("h1")

        if h1:
            title = self._clean_text(
                h1.get_text(" ", strip=True)
            )

            if title:
                return title

        # title HTML
        if soup.title:
            title = self._clean_text(
                soup.title.get_text(
                    " ",
                    strip=True,
                )
            )

            if title:
                return title

        return "Volkswagen ID.3"

    def _get_visible_text(
        self,
        soup: BeautifulSoup,
    ) -> str:

        for element in soup(
            [
                "script",
                "style",
                "noscript",
                "svg",
            ]
        ):
            element.decompose()

        return self._clean_text(
            soup.get_text(
                "\n",
                strip=True,
            )
        )

    @staticmethod
    def _clean_text(
        value: str,
    ) -> str:

        return re.sub(
            r"\s+",
            " ",
            value or "",
        ).strip()

    @staticmethod
    def _parse_integer(
        value: Any,
    ) -> int | None:

        if value is None:
            return None

        if isinstance(value, bool):
            return None

        if isinstance(value, (int, float)):
            return int(value)

        text = str(value)

        match = re.search(
            r'\d[\d\.\s]*',
            text,
        )

        if not match:
            return None

        raw = match.group(0)

        # Migliaia italiane:
        # 26.173 -> 26173
        # 40 698 -> 40698
        raw = raw.replace(
            ".",
            "",
        ).replace(
            " ",
            "",
        )

        try:
            return int(raw)
        except ValueError:
            return None

    @staticmethod
    def _parse_european_number(
        value: str,
    ) -> float | None:

        if not value:
            return None

        text = str(value).strip()

        # Rimuove simboli non numerici tranne . e ,
        text = re.sub(
            r"[^\d\.,]",
            "",
            text,
        )

        if not text:
            return None

        # Caso italiano:
        # 28.300 -> 28300
        # 28.300,50 -> 28300.50
        if "." in text and "," in text:
            text = text.replace(
                ".",
                "",
            ).replace(
                ",",
                ".",
            )

        elif "." in text:
            parts = text.split(".")

            if (
                len(parts) == 2
                and len(parts[1]) == 3
            ):
                text = "".join(parts)

        elif "," in text:
            parts = text.split(",")

            if (
                len(parts) == 2
                and len(parts[1]) == 3
            ):
                text = "".join(parts)
            else:
                text = text.replace(
                    ",",
                    ".",
                )

        try:
            return float(text)

        except ValueError:
            return None

    @staticmethod
    def _normalize_listing_url(
        url: str,
    ) -> str | None:

        if not url:
            return None

        url = url.strip()

        if url.startswith("/"):
            url = urljoin(
                AutoScout24Scraper.BASE_URL,
                url,
            )

        # Rimuove querystring e fragment.
        url = url.split("?", 1)[0]
        url = url.split("#", 1)[0]

        if not AutoScout24Scraper._looks_like_listing_url(
            url
        ):
            return None

        return url

    @staticmethod
    def _looks_like_listing_url(
        url: str,
    ) -> bool:

        return (
            "autoscout24.it/offerta/"
            in url
            and len(url) > 40
        )

    @staticmethod
    def _looks_like_search_page_url(
        url: str,
    ) -> bool:

        return (
            "autoscout24.it/lst/"
            in url
        )

    @staticmethod
    def _make_listing_id(
        url: str,
    ) -> str:

        return hashlib.sha1(
            url.encode("utf-8")
        ).hexdigest()[:16]
