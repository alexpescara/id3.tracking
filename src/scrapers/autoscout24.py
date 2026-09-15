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


PRICE_RE = re.compile(
    r"(?:€\s*)?(\d{1,3}(?:[.\s]\d{3})+|\d{4,6})(?:\s*€)?",
    re.IGNORECASE,
)

KM_RE = re.compile(
    r"(\d{1,3}(?:[.\s]\d{3})+|\d{4,7})\s*km",
    re.IGNORECASE,
)

YEAR_RE = re.compile(r"\b(20\d{2})\b")

BATTERY_RE = re.compile(
    r"\b(5[89]|6[0-9]|7[0-9]|8[0-9]|9[0-9]|1[0-2][0-9])\s*kWh\b",
    re.IGNORECASE,
)

POWER_RE = re.compile(
    r"\b(\d{2,3})\s*(?:CV|PS|hp)\b",
    re.IGNORECASE,
)


class AutoScout24Scraper(BaseScraper):
    """
    Scraper pubblico AutoScout24 basato su Playwright.

    Non tenta di bypassare CAPTCHA, autenticazione o sistemi
    anti-bot. Se AutoScout24 non restituisce normalmente i dati,
    il contenuto viene semplicemente analizzato per quanto possibile.
    """

    def search(self, search_url: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        scraper_cfg = self.config.get("scraper", {})

        headless = scraper_cfg.get("headless", True)
        timeout_ms = int(scraper_cfg.get("timeout_ms", 30000))
        delay_seconds = float(scraper_cfg.get("delay_seconds", 2.5))
        max_pages = int(scraper_cfg.get("max_pages", 3))
        user_agent = scraper_cfg.get("user_agent")

        print(f"AutoScout24: apertura {search_url}")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)

            context_kwargs = {
                "locale": "it-IT",
                "viewport": {
                    "width": 1440,
                    "height": 1000,
                },
            }

            if user_agent:
                context_kwargs["user_agent"] = user_agent

            context = browser.new_context(**context_kwargs)

            page = context.new_page()
            page.set_default_timeout(timeout_ms)

            try:
                page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )

                print(f"Pagina caricata: {page.url}")

                # Lasciamo tempo al rendering JavaScript.
                page.wait_for_timeout(4000)

                self._dismiss_common_consent(page)

                # Un secondo piccolo intervallo dopo l'eventuale
                # chiusura del banner cookie.
                page.wait_for_timeout(1500)

                for page_no in range(1, max_pages + 1):
                    print(f"Analisi pagina {page_no}/{max_pages}")

                    html = page.content()

                    print(f"HTML ricevuto: {len(html):,} caratteri")

                    page_results = self._parse_search_page(
                        html,
                        page.url,
                    )

                    print(
                        f"Annunci trovati nella pagina: "
                        f"{len(page_results)}"
                    )

                    results.extend(page_results)

                    if page_no >= max_pages:
                        break

                    next_url = self._find_next_page(page)

                    if not next_url:
                        print("Nessuna pagina successiva trovata.")
                        break

                    print(f"Pagina successiva: {next_url}")

                    time.sleep(delay_seconds)

                    page.goto(
                        next_url,
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )

                    page.wait_for_timeout(3500)

            except Exception as exc:
                print(
                    "Errore durante lo scraping AutoScout24: "
                    f"{type(exc).__name__}: {exc}"
                )

            finally:
                context.close()
                browser.close()

        results = self._deduplicate(results)

        print(f"Totale annunci unici raccolti: {len(results)}")

        return results

    @staticmethod
    def _dismiss_common_consent(page) -> None:
        """
        Prova a chiudere i principali banner cookie/consenso.
        Non considera il fallimento un errore.
        """

        selectors = [
            'button:has-text("Accetta tutto")',
            'button:has-text("Accetta")',
            'button:has-text("Accetta tutti")',
            'button:has-text("Accept all")',
            'button:has-text("Accept")',
        ]

        for selector in selectors:
            try:
                locator = page.locator(selector)

                if locator.count() > 0:
                    locator.first.click(timeout=2000)

                    print("Banner consenso chiuso.")

                    page.wait_for_timeout(700)

                    return

            except Exception:
                pass

    @staticmethod
    def _find_next_page(page) -> str | None:
        """
        Cerca il collegamento alla pagina successiva.
        """

        selectors = [
            'a[aria-label*="pagina successiva" i]',
            'a[aria-label*="next" i]',
            'a[title*="successiva" i]',
            'a[rel="next"]',
        ]

        for selector in selectors:
            try:
                locator = page.locator(selector)

                if locator.count() == 0:
                    continue

                href = locator.first.get_attribute("href")

                if href:
                    return urljoin(page.url, href)

            except Exception:
                pass

        return None

    def _parse_search_page(
        self,
        html: str,
        source_url: str,
    ) -> list[dict[str, Any]]:

        soup = BeautifulSoup(html, "lxml")

        results: list[dict[str, Any]] = []

        # ---------------------------------------------------------
        # 1. Metodo principale: __NEXT_DATA__
        # ---------------------------------------------------------

        next_data = self._extract_next_data(soup)

        if next_data:
            print("__NEXT_DATA__ trovato.")

            extracted = self._extract_from_next_data(
                next_data,
                source_url,
            )

            print(
                f"Annunci estratti da __NEXT_DATA__: "
                f"{len(extracted)}"
            )

            results.extend(extracted)

        # ---------------------------------------------------------
        # 2. JSON-LD
        # ---------------------------------------------------------

        jsonld_results = self._extract_jsonld(
            soup,
            source_url,
        )

        if jsonld_results:
            print(
                f"Annunci estratti da JSON-LD: "
                f"{len(jsonld_results)}"
            )

            results.extend(jsonld_results)

        # ---------------------------------------------------------
        # 3. Fallback HTML
        # ---------------------------------------------------------

        if not results:
            fallback_results = self._extract_from_links(
                soup,
                source_url,
            )

            print(
                f"Annunci estratti dal fallback HTML: "
                f"{len(fallback_results)}"
            )

            results.extend(fallback_results)

        return [
            item
            for item in results
            if item.get("url")
        ]

    @staticmethod
    def _extract_next_data(
        soup: BeautifulSoup,
    ) -> dict[str, Any] | None:

        script = soup.find(
            "script",
            id="__NEXT_DATA__",
        )

        if not script:
            return None

        try:
            raw = script.string or script.get_text()

            if not raw.strip():
                return None

            data = json.loads(raw)

            if isinstance(data, dict):
                return data

        except Exception as exc:
            print(
                "Errore parsing __NEXT_DATA__: "
                f"{type(exc).__name__}: {exc}"
            )

        return None

    def _extract_from_next_data(
        self,
        data: dict[str, Any],
        source_url: str,
    ) -> list[dict[str, Any]]:

        results: list[dict[str, Any]] = []

        # AutoScout24 può cambiare leggermente la posizione
        # dell'array degli annunci. Per questo cerchiamo
        # ricorsivamente oggetti che abbiano caratteristiche
        # tipiche di un annuncio.

        candidates = self._find_listing_objects(data)

        seen_urls: set[str] = set()

        for obj in candidates:
            item = self._listing_from_object(
                obj,
                source_url,
            )

            if not item:
                continue

            url = item.get("url")

            if not url:
                continue

            if url in seen_urls:
                continue

            seen_urls.add(url)

            results.append(item)

        return results

    def _find_listing_objects(
        self,
        value: Any,
    ) -> list[dict[str, Any]]:

        found: list[dict[str, Any]] = []

        if isinstance(value, dict):

            # Possibili indicatori di un oggetto listing.
            keys_lower = {
                str(k).lower()
                for k in value.keys()
            }

            has_url = any(
                key in keys_lower
                for key in (
                    "url",
                    "listingurl",
                    "detailurl",
                )
            )

            has_vehicle_data = any(
                key in keys_lower
                for key in (
                    "vehicle",
                    "make",
                    "model",
                    "price",
                    "mileage",
                    "mileagekm",
                    "firstregistration",
                    "registration",
                )
            )

            if has_url and has_vehicle_data:
                found.append(value)

            for child in value.values():
                found.extend(
                    self._find_listing_objects(child)
                )

        elif isinstance(value, list):

            for child in value:
                found.extend(
                    self._find_listing_objects(child)
                )

        return found

    def _listing_from_object(
        self,
        obj: dict[str, Any],
        source_url: str,
    ) -> dict[str, Any] | None:

        url = self._get_first(
            obj,
            [
                "url",
                "listingUrl",
                "listingURL",
                "detailUrl",
                "detailURL",
            ],
        )

        if not url:
            return None

        url = urljoin(source_url, str(url))

        # Evitiamo link non pertinenti.
        if "autoscout24" not in url.lower():
            return None

        title = self._get_first(
            obj,
            [
                "title",
                "name",
                "description",
                "version",
            ],
        )

        price = self._get_nested_or_first(
            obj,
            [
                "price",
                "priceValue",
                "priceEur",
                "offers.price",
            ],
        )

        mileage = self._get_nested_or_first(
            obj,
            [
                "mileage",
                "mileageKm",
                "mileageValue",
                "vehicle.mileage",
                "vehicle.mileageKm",
            ],
        )

        year = self._get_nested_or_first(
            obj,
            [
                "firstRegistration",
                "firstRegistrationDate",
                "registrationYear",
                "year",
                "vehicle.firstRegistration",
            ],
        )

        power = self._get_nested_or_first(
            obj,
            [
                "powerHp",
                "power",
                "vehicle.power",
            ],
        )

        battery = self._get_nested_or_first(
            obj,
            [
                "batteryKwh",
                "batteryCapacity",
                "batteryCapacityKwh",
                "vehicle.batteryKwh",
            ],
        )

        description = self._get_first(
            obj,
            [
                "description",
                "equipment",
                "version",
            ],
        )

        raw_text = json.dumps(
            obj,
            ensure_ascii=False,
        )

        return self._normalise(
            {
                "url": url,
                "title": title or "Volkswagen ID.3",
                "description": description or "",
                "price_raw": price,
                "mileage_raw": mileage,
                "year_raw": year,
                "power_raw": power,
                "battery_raw": battery,
                "raw": raw_text,
            }
        )

    @staticmethod
    def _get_first(
        obj: dict[str, Any],
        keys: list[str],
    ) -> Any:

        for key in keys:
            if key in obj and obj[key] not in (
                None,
                "",
                [],
                {},
            ):
                return obj[key]

        return None

    @staticmethod
    def _get_nested_or_first(
        obj: dict[str, Any],
        paths: list[str],
    ) -> Any:

        for path in paths:
            current: Any = obj

            try:
                for part in path.split("."):
                    if not isinstance(current, dict):
                        current = None
                        break

                    current = current.get(part)

                if current not in (
                    None,
                    "",
                    [],
                    {},
                ):
                    return current

            except Exception:
                continue

        return None

    def _extract_jsonld(
        self,
        soup: BeautifulSoup,
        source_url: str,
    ) -> list[dict[str, Any]]:

        results: list[dict[str, Any]] = []

        for script in soup.find_all(
            "script",
            type="application/ld+json",
        ):

            try:
                raw = script.string or script.get_text()

                if not raw.strip():
                    continue

                data = json.loads(raw)

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
                        t in {
                            "Car",
                            "Vehicle",
                            "Product",
                        }
                        for t in obj_type
                    )
                else:
                    valid_type = obj_type in {
                        "Car",
                        "Vehicle",
                        "Product",
                    }

                if not valid_type:
                    continue

                offers = obj.get("offers") or {}

                url = obj.get("url") or source_url

                results.append(
                    self._normalise(
                        {
                            "url": url,
                            "title": obj.get(
                                "name",
                                "Volkswagen ID.3",
                            ),
                            "description": obj.get(
                                "description",
                                "",
                            ),
                            "price_raw": (
                                offers.get("price")
                                if isinstance(
                                    offers,
                                    dict,
                                )
                                else None
                            ),
                            "mileage_raw": (
                                self._jsonld_mileage(obj)
                            ),
                            "year_raw": (
                                self._jsonld_year(obj)
                            ),
                            "raw": json.dumps(
                                obj,
                                ensure_ascii=False,
                            ),
                        }
                    )
                )

        return results

    @staticmethod
    def _jsonld_mileage(
        obj: dict[str, Any],
    ) -> Any:

        mileage = obj.get(
            "mileageFromOdometer"
        )

        if isinstance(mileage, dict):
            return mileage.get("value")

        return mileage

    @staticmethod
    def _jsonld_year(
        obj: dict[str, Any],
    ) -> Any:

        return (
            obj.get("vehicleModelDate")
            or obj.get("productionDate")
            or obj.get("dateVehicleFirstRegistered")
        )

    def _extract_from_links(
        self,
        soup: BeautifulSoup,
        source_url: str,
    ) -> list[dict[str, Any]]:

        results: list[dict[str, Any]] = []

        seen: set[str] = set()

        for link in soup.find_all(
            "a",
            href=True,
        ):

            href = str(link.get("href", ""))

            text = " ".join(
                link.stripped_strings
            )

            combined = (
                f"{text} {href}"
            ).lower()

            # Cerchiamo sia /annunci/ sia /offers/
            # perché AutoScout24 può usare URL differenti.
            if (
                "/annunci/" not in combined
                and "/offers/" not in combined
            ):
                continue

            if "id.3" not in combined:
                continue

            url = urljoin(
                source_url,
                href,
            )

            if url in seen:
                continue

            seen.add(url)

            results.append(
                self._normalise(
                    {
                        "url": url,
                        "title": text[:300],
                        "description": text,
                        "price_raw": None,
                        "mileage_raw": None,
                        "year_raw": None,
                        "raw": text,
                    }
                )
            )

        return results

    def _normalise(
        self,
        item: dict[str, Any],
    ) -> dict[str, Any]:

        raw = str(
            item.get("raw", "")
        )

        title = str(
            item.get("title", "")
        )

        description = str(
            item.get("description", "")
        )

        combined = (
            f"{title} "
            f"{description} "
            f"{raw}"
        )

        price = self._number(
            item.get("price_raw")
        )

        mileage = self._number(
            item.get("mileage_raw")
        )

        year = self._extract_year(
            item.get("year_raw")
        )

        power = self._number(
            item.get("power_raw")
        )

        battery = self._number(
            item.get("battery_raw")
        )

        if price is None:
            price = self._extract_price(
                combined
            )

        if mileage is None:
            mileage = self._extract_mileage(
                combined
            )

        if year is None:
            year_match = YEAR_RE.search(
                combined
            )

            if year_match:
                year = int(
                    year_match.group(1)
                )

        if battery is None:
            battery_match = BATTERY_RE.search(
                combined
            )

            if battery_match:
                battery = float(
                    battery_match.group(1)
                )

        if power is None:
            power_match = POWER_RE.search(
                combined
            )

            if power_match:
                power = int(
                    power_match.group(1)
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
            "seller": None,
            "collected_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
        }

    @staticmethod
    def _extract_price(
        text: str,
    ) -> float | None:

        # Prima cerchiamo il simbolo euro.
        match = PRICE_RE.search(text)

        if not match:
            return None

        value = match.group(1)

        return AutoScout24Scraper._number(
            value
        )

    @staticmethod
    def _extract_mileage(
        text: str,
    ) -> float | None:

        match = KM_RE.search(text)

        if not match:
            return None

        return AutoScout24Scraper._number(
            match.group(1)
        )

    @staticmethod
    def _extract_year(
        value: Any,
    ) -> int | None:

        if value is None:
            return None

        match = YEAR_RE.search(
            str(value)
        )

        if not match:
            return None

        return int(
            match.group(1)
        )

    @staticmethod
    def _number(
        value: Any,
    ) -> float | None:

        if value is None:
            return None

        if isinstance(
            value,
            bool,
        ):
            return None

        if isinstance(
            value,
            (int, float),
        ):
            return float(value)

        text = str(value).strip()

        if not text:
            return None

        # Rimuove simboli e mantiene cifre,
        # punto, virgola e segno.
        text = re.sub(
            r"[^\d,.\-]",
            "",
            text,
        )

        if not text:
            return None

        # Formato italiano:
        # 23.900 -> 23900
        # 23.900,50 -> 23900.50
        if "," in text and "." in text:
            text = text.replace(
                ".",
                "",
            ).replace(
                ",",
                ".",
            )

        # 23,900 -> 23900 oppure 23,5 -> 23.5
        elif "," in text:
            parts = text.split(",")

            if (
                len(parts) == 2
                and len(parts[1]) == 3
            ):
                text = (
                    parts[0]
                    + parts[1]
                )
            else:
                text = text.replace(
                    ",",
                    ".",
                )

        # 23.900 -> 23900
        elif "." in text:
            parts = text.split(".")

            if (
                len(parts) == 2
                and len(parts[1]) == 3
            ):
                text = (
                    parts[0]
                    + parts[1]
                )

        try:
            return float(text)

        except ValueError:
            return None

    @staticmethod
    def _listing_id(
        url: str,
    ) -> str:

        return hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()[:16]

    @staticmethod
    def _deduplicate(
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:

        unique: dict[str, dict[str, Any]] = {}

        for item in items:

            listing_id = item.get(
                "listing_id"
            )

            if not listing_id:
                continue

            unique[listing_id] = item

        return list(
            unique.values()
        )
