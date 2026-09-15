from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


class AutoScout24Scraper:
    BASE_URL = "https://www.autoscout24.it"

    def __init__(self, config: dict):
        self.config = config
        self.scraper_cfg = config.get("scraper", {})

        self.headless = self.scraper_cfg.get("headless", True)
        self.timeout_ms = int(
            self.scraper_cfg.get("timeout_ms", 30000)
        )
        self.delay_seconds = float(
            self.scraper_cfg.get("delay_seconds", 2.5)
        )
        self.max_pages = int(
            self.scraper_cfg.get("max_pages", 5)
        )
        self.max_detail_pages = int(
            self.scraper_cfg.get("max_detail_pages", 30)
        )

        self.user_agent = self.scraper_cfg.get(
            "user_agent",
            "ID3-Market-Monitor/0.1 (open-source research project)",
        )

    # ================================================================
    # PUBLIC
    # ================================================================

    def search(self, search_url: str) -> list[dict[str, Any]]:
        """
        Cerca gli annunci sulla pagina risultati e successivamente,
        quando possibile, apre le singole schede.

        La pagina risultati rimane la fonte primaria per:
        - URL
        - titolo
        - prezzo
        - km
        - anno
        - potenza
        - batteria

        La pagina dettaglio viene utilizzata per arricchire:
        - descrizione
        - venditore
        - equipaggiamento
        - display 12"/12,9"
        """

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless
            )

            context = browser.new_context(
                user_agent=self.user_agent,
                locale="it-IT",
                timezone_id="Europe/Rome",
                viewport={
                    "width": 1440,
                    "height": 1000,
                },
            )

            page = context.new_page()

            page.set_default_timeout(
                self.timeout_ms
            )

            try:
                listings = self._collect_result_pages(
                    page,
                    search_url,
                )

                print(
                    f"Annunci individuati dalla pagina risultati: "
                    f"{len(listings)}"
                )

                if not listings:
                    return []

                # ----------------------------------------------------
                # Arricchimento con pagina dettaglio
                # ----------------------------------------------------

                detail_count = min(
                    len(listings),
                    self.max_detail_pages,
                )

                for index in range(detail_count):

                    listing = listings[index]
                    url = listing.get("url")

                    if not url:
                        continue

                    print(
                        f"[Dettaglio {index + 1}/{detail_count}] "
                        f"{url}"
                    )

                    try:
                        detail = self._scrape_detail_page(
                            page,
                            url,
                        )

                        if detail:
                            self._merge_detail_data(
                                listing,
                                detail,
                            )

                    except Exception as exc:
                        print(
                            f"  Dettaglio non disponibile: "
                            f"{type(exc).__name__}: {exc}"
                        )

                    if index < detail_count - 1:
                        time.sleep(
                            self.delay_seconds
                        )

                return listings

            finally:
                context.close()
                browser.close()

    # ================================================================
    # PAGINA RISULTATI
    # ================================================================

    def _collect_result_pages(
        self,
        page,
        search_url: str,
    ) -> list[dict[str, Any]]:

        all_listings: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        current_url = search_url

        for page_number in range(
            1,
            self.max_pages + 1,
        ):
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

            # AutoScout può completare parte del rendering
            # dopo il DOMContentLoaded.
            try:
                page.wait_for_timeout(3000)
            except Exception:
                pass

            html = page.content()

            soup = BeautifulSoup(
                html,
                "lxml",
            )

            jsonld = self._extract_jsonld_objects(
                soup
            )

            next_data = self._extract_next_data(
                soup
            )

            # --------------------------------------------------------
            # Metodo 1: JSON-LD / dati strutturati
            # --------------------------------------------------------

            page_listings = self._extract_listings_from_jsonld(
                jsonld
            )

            # --------------------------------------------------------
            # Metodo 2: NEXT_DATA
            # --------------------------------------------------------

            next_listings = self._extract_listings_from_next_data(
                next_data
            )

            page_listings.extend(
                next_listings
            )

            # --------------------------------------------------------
            # Metodo 3: HTML delle card
            # --------------------------------------------------------

            html_listings = self._extract_listings_from_html(
                soup
            )

            page_listings.extend(
                html_listings
            )

            # --------------------------------------------------------
            # Deduplicazione
            # --------------------------------------------------------

            unique_page_listings = []

            local_seen = set()

            for item in page_listings:

                url = self._normalize_url(
                    item.get("url")
                )

                if not url:
                    continue

                item["url"] = url

                listing_id = self._make_listing_id(
                    url
                )

                if listing_id in local_seen:
                    continue

                local_seen.add(listing_id)

                if listing_id in seen_ids:
                    continue

                seen_ids.add(listing_id)

                item["listing_id"] = listing_id

                unique_page_listings.append(
                    item
                )

            print(
                f"  Annunci trovati nella pagina: "
                f"{len(unique_page_listings)}"
            )

            all_listings.extend(
                unique_page_listings
            )

            # --------------------------------------------------------
            # Pagina successiva
            # --------------------------------------------------------

            next_url = self._find_next_page(
                soup,
                current_url,
            )

            if not next_url:
                break

            if next_url == current_url:
                break

            current_url = next_url

            time.sleep(
                self.delay_seconds
            )

        return all_listings

    # ================================================================
    # ESTRAZIONE ANNUNCI DA JSON-LD
    # ================================================================

    def _extract_listings_from_jsonld(
        self,
        objects: list[Any],
    ) -> list[dict[str, Any]]:

        results = []

        for obj in objects:

            if not isinstance(obj, dict):
                continue

            # ItemList AutoScout
            item_list = obj.get(
                "itemListElement"
            )

            if isinstance(item_list, list):

                for item in item_list:

                    if not isinstance(item, dict):
                        continue

                    item_obj = item.get(
                        "item"
                    )

                    if isinstance(
                        item_obj,
                        dict,
                    ):
                        parsed = self._parse_listing_object(
                            item_obj
                        )

                        if parsed:
                            results.append(
                                parsed
                            )

            # Singolo veicolo
            parsed = self._parse_listing_object(
                obj
            )

            if parsed:
                results.append(
                    parsed
                )

        return results

    def _parse_listing_object(
        self,
        obj: dict[str, Any],
    ) -> dict[str, Any] | None:

        url = obj.get(
            "url"
        )

        if not url:
            return None

        if not self._looks_like_listing_url(
            str(url)
        ):
            return None

        title = (
            obj.get("name")
            or obj.get("title")
            or "Volkswagen ID.3"
        )

        offers = obj.get(
            "offers"
        )

        price = None

        if isinstance(
            offers,
            dict,
        ):
            price = self._parse_price(
                offers.get("price")
            )

        mileage = None

        mileage_obj = obj.get(
            "mileageFromOdometer"
        )

        if isinstance(
            mileage_obj,
            dict,
        ):
            mileage = self._parse_mileage(
                mileage_obj.get("value")
            )

        year = self._extract_year_from_value(
            obj.get(
                "dateVehicleFirstRegistered"
            )
        )

        if year is None:
            year = self._extract_year_from_value(
                obj.get("vehicleConfiguration")
            )

        return {
            "url": str(url),
            "title": self._clean_text(
                str(title)
            ),
            "price_eur": price,
            "mileage_km": mileage,
            "registration_year": year,
            "battery_kwh": self._parse_battery_from_text(
                str(title)
            ),
            "power_hp": self._parse_hp_from_text(
                str(title)
            ),
            "description": self._clean_text(
                str(
                    obj.get(
                        "description",
                        "",
                    )
                )
            ),
            "seller": self._extract_seller_from_object(
                obj
            ),
        }

    # ================================================================
    # ESTRAZIONE DA NEXT_DATA
    # ================================================================

    def _extract_listings_from_next_data(
        self,
        next_data: Any,
    ) -> list[dict[str, Any]]:

        if not next_data:
            return []

        results = []

        for obj in self._walk_objects(
            next_data
        ):

            if not isinstance(obj, dict):
                continue

            url = self._find_first_string(
                obj,
                {
                    "url",
                    "detailUrl",
                    "detailURL",
                    "listingUrl",
                    "vehicleUrl",
                },
            )

            if not url:
                continue

            if not self._looks_like_listing_url(
                url
            ):
                continue

            title = self._find_first_string(
                obj,
                {
                    "title",
                    "name",
                    "vehicleName",
                    "modelName",
                },
            )

            # Non accettiamo oggetti completamente vuoti.
            if not title:
                title = "Volkswagen ID.3"

            price = self._find_first_price(
                obj
            )

            mileage = self._find_first_mileage(
                obj
            )

            year = self._find_first_year(
                obj
            )

            battery = self._parse_battery_from_text(
                title
            )

            power = self._parse_hp_from_text(
                title
            )

            if power is None:
                power = self._parse_hp_from_object(
                    obj
                )

            results.append(
                {
                    "url": url,
                    "title": self._clean_text(
                        title
                    ),
                    "price_eur": price,
                    "mileage_km": mileage,
                    "registration_year": year,
                    "battery_kwh": battery,
                    "power_hp": power,
                    "description": "",
                    "seller": "",
                }
            )

        return results

    # ================================================================
    # ESTRAZIONE HTML CARD
    # ================================================================

    def _extract_listings_from_html(
        self,
        soup: BeautifulSoup,
    ) -> list[dict[str, Any]]:

        results = []

        # Non utilizziamo un selettore rigido.
        # Cerchiamo tutti i link e poi risaliamo al contenitore
        # della card.
        links = soup.find_all(
            "a",
            href=True,
        )

        for link in links:

            href = link.get(
                "href",
                "",
            )

            if not self._looks_like_listing_url(
                href
            ):
                continue

            url = self._normalize_url(
                href
            )

            if not url:
                continue

            # Risaliamo alcuni livelli per trovare il testo
            # della card.
            container = link

            for _ in range(6):

                if not container:
                    break

                text = self._clean_text(
                    container.get_text(
                        " ",
                        strip=True,
                    )
                )

                # Una card normalmente contiene prezzo + km
                # oppure anno + km.
                if (
                    len(text) > 50
                    and (
                        "€" in text
                        or "km" in text.lower()
                        or "kwh" in text.lower()
                    )
                ):
                    break

                container = container.parent

            if not container:
                container = link

            text = self._clean_text(
                container.get_text(
                    " ",
                    strip=True,
                )
            )

            title = self._extract_card_title(
                container
            )

            if not title:
                title = self._clean_text(
                    link.get_text(
                        " ",
                        strip=True,
                    )
                )

            price = self._extract_price_from_text(
                text
            )

            mileage = self._extract_mileage_from_text(
                text
            )

            year = self._extract_month_year(
                text
            )

            battery = self._parse_battery_from_text(
                title
            )

            if battery is None:
                battery = self._parse_battery_from_text(
                    text
                )

            power = self._parse_hp_from_text(
                title
            )

            if power is None:
                power = self._parse_hp_from_text(
                    text
                )

            # Se troviamo kW ma non CV, convertiamo.
            if power is None:
                kw = self._parse_kw_from_text(
                    title
                )

                if kw is None:
                    kw = self._parse_kw_from_text(
                        text
                    )

                if kw is not None:
                    power = self._kw_to_hp(
                        kw
                    )

            results.append(
                {
                    "url": url,
                    "title": title,
                    "price_eur": price,
                    "mileage_km": mileage,
                    "registration_year": year,
                    "battery_kwh": battery,
                    "power_hp": power,
                    "description": "",
                    "seller": "",
                }
            )

        return results

    # ================================================================
    # PAGINA DETTAGLIO
    # ================================================================

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
        except Exception:
            return None

        try:
            page.wait_for_timeout(
                2500
            )
        except Exception:
            pass

        html = page.content()

        soup = BeautifulSoup(
            html,
            "lxml",
        )

        jsonld = self._extract_jsonld_objects(
            soup
        )

        next_data = self._extract_next_data(
            soup
        )

        visible_text = self._get_visible_text(
            soup
        )

        title = self._extract_detail_title(
            soup,
            jsonld,
            next_data,
        )

        description = self._extract_description(
            soup,
            jsonld,
        )

        seller = self._extract_seller(
            soup,
            jsonld,
            next_data,
        )

        equipment = self._extract_equipment(
            soup,
            visible_text,
        )

        infotainment_candidate, evidence = (
            self._detect_129_infotainment(
                title,
                description,
                equipment,
                visible_text,
            )
        )

        # Dati tecnici eventualmente presenti
        # nella scheda dettaglio.
        price = self._extract_price(
            jsonld,
            next_data,
            visible_text,
        )

        mileage = self._extract_mileage_detail(
            jsonld,
            next_data,
            visible_text,
        )

        year = self._extract_year_detail(
            jsonld,
            next_data,
            visible_text,
        )

        battery = self._parse_battery_from_text(
            title
        )

        if battery is None:
            battery = self._parse_battery_from_text(
                visible_text
            )

        power = self._parse_hp_from_text(
            title
        )

        if power is None:
            power = self._parse_hp_from_text(
                visible_text
            )

        if power is None:
            kw = self._parse_kw_from_text(
                title
            )

            if kw is None:
                kw = self._parse_kw_from_text(
                    visible_text
                )

            if kw is not None:
                power = self._kw_to_hp(
                    kw
                )

        return {
            "title": title,
            "price_eur": price,
            "mileage_km": mileage,
            "registration_year": year,
            "battery_kwh": battery,
            "power_hp": power,
            "description": description,
            "seller": seller,
            "equipment": equipment,
            "infotainment_129_candidate": infotainment_candidate,
            "classification_evidence": evidence,
        }

    # ================================================================
    # MERGE
    # ================================================================

    def _merge_detail_data(
        self,
        listing: dict[str, Any],
        detail: dict[str, Any],
    ) -> None:
    
        # La pagina dettaglio è considerata più affidabile
        # della card risultati per i dati tecnici.
        for field in [
            "price_eur",
            "mileage_km",
            "registration_year",
            "battery_kwh",
            "power_hp",
        ]:
            new_value = detail.get(field)
    
            if not self._is_empty_value(new_value):
                listing[field] = new_value
    
        # Titolo: preferiamo sempre quello del dettaglio
        # se identifica realmente una ID.3.
        detail_title = detail.get("title")
        current_title = listing.get("title")
    
        if detail_title:
            detail_lower = detail_title.lower()
    
            if (
                "id.3" in detail_lower
                or "id 3" in detail_lower
            ):
                if (
                    not current_title
                    or len(detail_title) > len(current_title)
                    or current_title.lower() == "volkswagen"
                ):
                    listing["title"] = detail_title
    
        if detail.get("description"):
            listing["description"] = detail["description"]
    
        if detail.get("seller"):
            listing["seller"] = detail["seller"]
    
        if detail.get("equipment"):
            equipment = self._clean_text(
                detail["equipment"]
            )
    
            if len(equipment) <= 3000:
                listing["equipment"] = equipment
    
        if (
            detail.get("infotainment_129_candidate")
            is not None
        ):
            listing[
                "infotainment_129_candidate"
            ] = detail[
                "infotainment_129_candidate"
            ]
    
            listing[
                "classification_evidence"
            ] = detail.get(
                "classification_evidence",
                "",
            )

    # ================================================================
    # PRICE
    # ================================================================

    def _extract_price(
        self,
        jsonld: list[Any],
        next_data: Any,
        text: str,
    ) -> float | None:

        for obj in jsonld:

            if not isinstance(obj, dict):
                continue

            offers = obj.get(
                "offers"
            )

            if isinstance(
                offers,
                dict,
            ):
                price = self._parse_price(
                    offers.get("price")
                )

                if price:
                    return price

        if next_data:

            for obj in self._walk_objects(
                next_data
            ):

                if not isinstance(obj, dict):
                    continue

                price = self._find_first_price(
                    obj
                )

                if price:
                    return price

        return self._extract_price_from_text(
            text
        )

    # ================================================================
    # MILEAGE / YEAR DETAIL
    # ================================================================

    def _extract_mileage_detail(
        self,
        jsonld: list[Any],
        next_data: Any,
        text: str,
    ) -> int | None:

        for obj in jsonld:

            if not isinstance(obj, dict):
                continue

            mileage = obj.get(
                "mileageFromOdometer"
            )

            if isinstance(
                mileage,
                dict,
            ):
                value = self._parse_mileage(
                    mileage.get(
                        "value"
                    )
                )

                if value is not None:
                    return value

        if next_data:

            value = self._find_first_mileage(
                next_data
            )

            if value is not None:
                return value

        return self._extract_mileage_from_text(
            text
        )

    def _extract_year_detail(
        self,
        jsonld: list[Any],
        next_data: Any,
        text: str,
    ) -> int | None:

        for obj in jsonld:

            if not isinstance(obj, dict):
                continue

            for key in [
                "dateVehicleFirstRegistered",
                "registrationDate",
                "firstRegistration",
            ]:

                year = self._extract_year_from_value(
                    obj.get(key)
                )

                if year:
                    return year

        if next_data:

            year = self._find_first_year(
                next_data
            )

            if year:
                return year

        return self._extract_month_year(
            text
        )

    # ================================================================
    # DESCRIPTION / SELLER / EQUIPMENT
    # ================================================================

    def _extract_description(
        self,
        soup: BeautifulSoup,
        jsonld: list[Any],
    ) -> str:
    
        generic_fragments = [
            "trova la tua volkswagen",
            "autoscout24",
            "passa al contenuto principale",
            "i miei aggiornamenti",
            "ricerca auto",
            "compra auto",
            "compra auto usate",
            "compra auto nuove",
            "ricerca concessionari",
            "inserisci un annuncio",
            "vendila a un rivenditore",
        ]
    
        def is_valid(value: str) -> bool:
            value = self._clean_text(
                value
            )
    
            if len(value) < 30:
                return False
    
            if len(value) > 3000:
                return False
    
            lower = value.lower()
    
            # Evita testo globale della pagina
            generic_count = sum(
                fragment in lower
                for fragment in generic_fragments
            )
    
            if generic_count >= 2:
                return False
    
            return True
    
        # ------------------------------------------------------------
        # JSON-LD
        # ------------------------------------------------------------
    
        for obj in jsonld:
    
            if not isinstance(
                obj,
                dict,
            ):
                continue
    
            value = obj.get(
                "description"
            )
    
            if not isinstance(
                value,
                str,
            ):
                continue
    
            value = self._clean_text(
                value
            )
    
            if is_valid(value):
                return value
    
        # ------------------------------------------------------------
        # Selettori specifici
        # ------------------------------------------------------------
    
        selectors = [
            '[data-testid="description"]',
            '[data-testid*="description"]',
            '[aria-label*="Descrizione" i]',
            '[class*="description" i]',
        ]
    
        candidates = []
    
        for selector in selectors:
    
            try:
    
                for element in soup.select(
                    selector
                ):
    
                    value = self._clean_text(
                        element.get_text(
                            " ",
                            strip=True,
                        )
                    )
    
                    if is_valid(value):
                        candidates.append(
                            value
                        )
    
            except Exception:
                continue
    
        if not candidates:
            return ""
    
        # Preferiamo descrizioni brevi e
        # plausibili rispetto a contenitori enormi.
        candidates = sorted(
            set(candidates),
            key=len,
        )
    
        return candidates[0]

    def _extract_seller(
        self,
        soup: BeautifulSoup,
        jsonld: list[Any],
        next_data: Any,
    ) -> str:
    
        # JSON-LD
        for obj in jsonld:
            if not isinstance(obj, dict):
                continue
    
            seller = obj.get("seller")
    
            if isinstance(seller, dict):
                name = seller.get("name")
    
                if isinstance(name, str):
                    name = self._clean_text(name)
    
                    if self._is_valid_seller(name):
                        return name
    
        # NEXT_DATA
        for obj in self._walk_objects(next_data):
            if not isinstance(obj, dict):
                continue
    
            for key in [
                "sellerName",
                "dealerName",
                "seller",
                "dealer",
                "companyName",
            ]:
                value = obj.get(key)
    
                if isinstance(value, dict):
                    value = (
                        value.get("name")
                        or value.get("displayName")
                    )
    
                if isinstance(value, str):
                    value = self._clean_text(value)
    
                    if self._is_valid_seller(value):
                        return value
    
        # Selettori mirati
        selectors = [
            '[data-testid="seller"]',
            '[data-testid="dealer"]',
            '[data-testid*="seller-name" i]',
            '[data-testid*="dealer-name" i]',
        ]
    
        for selector in selectors:
            try:
                for element in soup.select(selector):
                    value = self._clean_text(
                        element.get_text(
                            " ",
                            strip=True,
                        )
                    )
    
                    if self._is_valid_seller(value):
                        return value
    
            except Exception:
                continue
    
        return ""
    
    
    @staticmethod
    def _is_valid_seller(value: str) -> bool:
    
        if not value:
            return False
    
        if len(value) < 2:
            return False
    
        if len(value) > 200:
            return False
    
        lower = value.lower()
    
        invalid_fragments = [
            "autoscout24",
            "passa al contenuto",
            "ricerca auto",
            "compra auto",
            "trova la tua volkswagen",
            "i miei aggiornamenti",
        ]
    
        if any(
            fragment in lower
            for fragment in invalid_fragments
        ):
            return False
    
        return True

    def _extract_seller_from_object(
        self,
        obj: dict[str, Any],
    ) -> str:

        seller = obj.get(
            "seller"
        )

        if isinstance(
            seller,
            dict,
        ):
            value = seller.get(
                "name"
            )

            if value:
                return self._clean_text(
                    str(value)
                )

        return ""

    def _extract_equipment(
        self,
        soup: BeautifulSoup,
        text: str,
    ) -> str:
    
        pieces = []
    
        # ------------------------------------------------------------
        # Selettori specifici
        # ------------------------------------------------------------
    
        selectors = [
            '[data-testid="equipment"]',
            '[data-testid="vehicle-equipment"]',
            '[data-testid*="equipment-list" i]',
            '[aria-label*="Equipaggiamento" i]',
            '[aria-label*="Optional" i]',
        ]
    
        for selector in selectors:
    
            try:
    
                for element in soup.select(
                    selector
                ):
    
                    value = self._clean_text(
                        element.get_text(
                            " ",
                            strip=True,
                        )
                    )
    
                    if (
                        not value
                        or len(value) < 3
                        or len(value) > 2500
                    ):
                        continue
    
                    if value not in pieces:
                        pieces.append(
                            value
                        )
    
            except Exception:
                continue
    
        if pieces:
            return " | ".join(
                pieces
            )
    
        # ------------------------------------------------------------
        # Fallback:
        # estraiamo solo righe plausibilmente
        # relative all'equipaggiamento.
        # ------------------------------------------------------------
    
        keywords = [
            "ready 2 discover",
            "ready2discover",
            "12,9",
            "12.9",
            "touchscreen",
            "touch screen",
            "display",
            "schermo",
            "assistance pack",
            "comfort pack",
            "tech pack",
            "exterior pack",
            "interior pack",
            "park assist",
            "pompa di calore",
            "cerchi in lega",
            "head-up display",
            "matrix led",
            "travel assist",
            "lane assist",
            "adaptive cruise",
        ]
    
        lines = []
    
        for raw_line in text.splitlines():
    
            line = self._clean_text(
                raw_line
            )
    
            if not line:
                continue
    
            if len(line) > 500:
                continue
    
            lower = line.lower()
    
            if any(
                keyword in lower
                for keyword in keywords
            ):
    
                if line not in lines:
                    lines.append(
                        line
                    )
    
        return " | ".join(
            lines
        )

    # ================================================================
    # 12.9"
    # ================================================================

    def _detect_129_infotainment(
        self,
        title: str,
        description: str,
        equipment: str,
        visible_text: str,
    ) -> tuple[bool | None, str]:

        combined = " ".join(
            [
                title or "",
                description or "",
                equipment or "",
            ]
        )

        normalized = (
            combined
            .replace(
                "″",
                '"',
            )
            .replace(
                "”",
                '"',
            )
            .replace(
                "’",
                "'",
            )
        )

        # ------------------------------------------------------------
        # 12.9"
        # ------------------------------------------------------------

        patterns_129 = [
            r'\b12[.,]9\s*(?:["]|pollici|inch)',
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

                evidence = self._evidence(
                    normalized,
                    match.start(),
                    match.end(),
                )

                return True, evidence

        # ------------------------------------------------------------
        # 12"
        # ------------------------------------------------------------

        patterns_12 = [
            r'\b12\s*(?:["]|pollici|inch)',
            r'\b12\s*\'\'',
            r'30[.,]5\s*cm\s*\(\s*12',
        ]

        infotainment_words = [
            "display",
            "schermo",
            "touchscreen",
            "touch screen",
            "radio",
            "ready 2 discover",
            "ready2discover",
        ]

        for pattern in patterns_12:

            match = re.search(
                pattern,
                normalized,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            start = max(
                0,
                match.start() - 150,
            )

            end = min(
                len(normalized),
                match.end() + 150,
            )

            context = normalized[
                start:end
            ].lower()

            if any(
                word in context
                for word in infotainment_words
            ):

                evidence = self._evidence(
                    normalized,
                    match.start(),
                    match.end(),
                )

                return False, evidence

        return None, ""

    def _evidence(
        self,
        text: str,
        start: int,
        end: int,
    ) -> str:

        left = max(
            0,
            start - 120,
        )

        right = min(
            len(text),
            end + 180,
        )

        return self._clean_text(
            text[left:right]
        )

    # ================================================================
    # TITLE
    # ================================================================

    def _extract_detail_title(
        self,
        soup: BeautifulSoup,
        jsonld: list[Any],
        next_data: Any,
    ) -> str:
    
        # JSON-LD: accettiamo solo nomi che identificano realmente
        # il veicolo. Evitiamo valori generici come "Volkswagen".
        candidates = []
    
        for obj in jsonld:
            if not isinstance(obj, dict):
                continue
    
            name = obj.get("name")
    
            if not isinstance(name, str):
                continue
    
            name = self._clean_text(name)
    
            if not name:
                continue
    
            lower = name.lower()
    
            if "id.3" in lower or "id 3" in lower:
                candidates.append(name)
    
        # Preferiamo il titolo più informativo.
        if candidates:
            return max(candidates, key=len)
    
        # H1 della pagina
        h1 = soup.find("h1")
    
        if h1:
            title = self._clean_text(
                h1.get_text(
                    " ",
                    strip=True,
                )
            )
    
            if (
                "id.3" in title.lower()
                or "id 3" in title.lower()
            ):
                return title
    
        # Cerca nei dati NEXT_DATA
        for obj in self._walk_objects(next_data):
            if not isinstance(obj, dict):
                continue
    
            for key in [
                "title",
                "name",
                "vehicleName",
                "modelName",
            ]:
                value = obj.get(key)
    
                if not isinstance(value, str):
                    continue
    
                value = self._clean_text(value)
    
                if (
                    "id.3" in value.lower()
                    or "id 3" in value.lower()
                ):
                    return value
    
        # Ultimo fallback: title HTML
        if soup.title:
            title = self._clean_text(
                soup.title.get_text(
                    " ",
                    strip=True,
                )
            )
    
            if (
                "id.3" in title.lower()
                or "id 3" in title.lower()
            ):
                return title
    
        return "Volkswagen ID.3"

    # ================================================================
    # GENERIC JSON HELPERS
    # ================================================================

    def _extract_jsonld_objects(
        self,
        soup: BeautifulSoup,
    ) -> list[Any]:

        objects = []

        for script in soup.find_all(
            "script",
            attrs={
                "type": "application/ld+json"
            },
        ):

            raw = (
                script.string
                or script.get_text()
            )

            if not raw:
                continue

            try:
                data = json.loads(
                    raw.strip()
                )

                if isinstance(
                    data,
                    list,
                ):
                    objects.extend(
                        data
                    )
                else:
                    objects.append(
                        data
                    )

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

        raw = (
            script.string
            or script.get_text()
        )

        if not raw:
            return None

        try:
            return json.loads(
                raw
            )
        except Exception:
            return None

    def _walk_objects(
        self,
        obj: Any,
    ):

        yield obj

        if isinstance(
            obj,
            dict,
        ):

            for value in obj.values():
                yield from self._walk_objects(
                    value
                )

        elif isinstance(
            obj,
            list,
        ):

            for value in obj:
                yield from self._walk_objects(
                    value
                )

    def _find_first_string(
        self,
        obj: dict[str, Any],
        keys: set[str],
    ) -> str | None:

        normalized = {
            key.lower()
            for key in keys
        }

        for key, value in obj.items():

            if (
                key.lower()
                in normalized
                and isinstance(
                    value,
                    str,
                )
            ):

                if value.strip():
                    return value.strip()

        return None

    # ================================================================
    # NEXT DATA VALUES
    # ================================================================

    def _find_first_price(
        self,
        obj: Any,
    ) -> float | None:

        if isinstance(
            obj,
            dict,
        ):

            for key, value in obj.items():

                key_lower = key.lower()

                if key_lower in {
                    "price",
                    "pricevalue",
                    "listingprice",
                    "vehicleprice",
                }:

                    price = self._parse_price(
                        value
                    )

                    if (
                        price
                        and 3000
                        <= price
                        <= 200000
                    ):
                        return price

                result = self._find_first_price(
                    value
                )

                if result:
                    return result

        elif isinstance(
            obj,
            list,
        ):

            for value in obj:

                result = self._find_first_price(
                    value
                )

                if result:
                    return result

        return None

    def _find_first_mileage(
        self,
        obj: Any,
    ) -> int | None:

        if isinstance(
            obj,
            dict,
        ):

            for key, value in obj.items():

                key_lower = key.lower()

                if key_lower in {
                    "mileage",
                    "mileagekm",
                    "kilometers",
                    "kilometres",
                    "odometer",
                }:

                    result = self._parse_mileage(
                        value
                    )

                    if result is not None:
                        return result

                result = self._find_first_mileage(
                    value
                )

                if result is not None:
                    return result

        elif isinstance(
            obj,
            list,
        ):

            for value in obj:

                result = self._find_first_mileage(
                    value
                )

                if result is not None:
                    return result

        return None

    def _find_first_year(
        self,
        obj: Any,
    ) -> int | None:

        if isinstance(
            obj,
            dict,
        ):

            for key, value in obj.items():

                key_lower = key.lower()

                if key_lower in {
                    "registrationdate",
                    "registrationyear",
                    "firstregistration",
                    "datefirstregistered",
                    "datevehiclefirstregistered",
                }:

                    year = self._extract_year_from_value(
                        value
                    )

                    if year:
                        return year

                result = self._find_first_year(
                    value
                )

                if result:
                    return result

        elif isinstance(
            obj,
            list,
        ):

            for value in obj:

                result = self._find_first_year(
                    value
                )

                if result:
                    return result

        return None

    # ================================================================
    # PARSING NUMERI
    # ================================================================

    def _parse_price(
        self,
        value: Any,
    ) -> float | None:

        if value is None:
            return None

        if isinstance(
            value,
            (int, float),
        ):

            value = float(value)

            if (
                3000
                <= value
                <= 200000
            ):
                return value

            return None

        text = str(value)

        match = re.search(
            r'\d[\d\.\s,]*',
            text,
        )

        if not match:
            return None

        value = self._parse_european_number(
            match.group(0)
        )

        if (
            value is not None
            and 3000
            <= value
            <= 200000
        ):
            return value

        return None

    def _parse_mileage(
        self,
        value: Any,
    ) -> int | None:

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

            value = int(value)

            if (
                0
                <= value
                <= 1000000
            ):
                return value

            return None

        match = re.search(
            r'\d[\d\.\s]*',
            str(value),
        )

        if not match:
            return None

        raw = (
            match.group(0)
            .replace(
                ".",
                "",
            )
            .replace(
                " ",
                "",
            )
        )

        try:
            value = int(
                raw
            )
        except ValueError:
            return None

        if (
            0
            <= value
            <= 1000000
        ):
            return value

        return None

    def _parse_battery_from_text(
        self,
        text: str,
    ) -> float | None:

        patterns = [
            r'\b(\d{2,3}(?:[.,]\d+)?)\s*kwh\b',
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:

                value = float(
                    match.group(1).replace(
                        ",",
                        ".",
                    )
                )

                if (
                    30
                    <= value
                    <= 150
                ):
                    return value

        return None

    def _parse_hp_from_text(
        self,
        text: str,
    ) -> int | None:
    
        if not text:
            return None
    
        matches = re.findall(
            r'\b(\d{2,3})\s*CV\b',
            text,
            flags=re.IGNORECASE,
        )
    
        values = []
    
        for value in matches:
            hp = int(value)
    
            if 50 <= hp <= 500:
                values.append(hp)
    
        if not values:
            matches = re.findall(
                r'\b(\d{2,3})\s*cavalli\b',
                text,
                flags=re.IGNORECASE,
            )
    
            for value in matches:
                hp = int(value)
    
                if 50 <= hp <= 500:
                    values.append(hp)
    
        if not values:
            return None
    
        # ID.3 Pro / Pro Performance:
        # 204 CV è il valore che vogliamo privilegiare
        # quando compare esplicitamente nel testo.
        if 204 in values:
            return 204
    
        # Evita di prendere automaticamente 95 CV quando
        # nel testo sono presenti altri valori tecnici.
        return values[0]

    def _parse_hp_from_object(
        self,
        obj: Any,
    ) -> int | None:

        if isinstance(
            obj,
            dict,
        ):

            for key, value in obj.items():

                if key.lower() in {
                    "horsepower",
                    "hp",
                    "cv",
                }:

                    result = self._parse_hp_from_text(
                        str(value)
                    )

                    if result:
                        return result

                result = self._parse_hp_from_object(
                    value
                )

                if result:
                    return result

        elif isinstance(
            obj,
            list,
        ):

            for value in obj:

                result = self._parse_hp_from_object(
                    value
                )

                if result:
                    return result

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

        for value in matches:

            kw = float(
                value.replace(
                    ",",
                    ".",
                )
            )

            if (
                30
                <= kw
                <= 400
            ):
                return kw

        return None

    @staticmethod
    def _kw_to_hp(
        kw: float,
    ) -> int:

        return round(
            kw * 1.35962
        )

    # ================================================================
    # PARSING TESTO CARD
    # ================================================================

    def _extract_price_from_text(
        self,
        text: str,
    ) -> float | None:

        patterns = [
            r'€\s*([0-9][0-9\.\s]*)',
            r'([0-9][0-9\.\s]*)\s*€',
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:

                value = self._parse_european_number(
                    match.group(1)
                )

                if (
                    value
                    and 3000
                    <= value
                    <= 200000
                ):
                    return value

        return None

    def _extract_mileage_from_text(
        self,
        text: str,
    ) -> int | None:

        match = re.search(
            r'(\d[\d\.\s]*)\s*km\b',
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            return None

        return self._parse_mileage(
            match.group(1)
        )

    def _extract_month_year(
        self,
        text: str,
    ) -> int | None:

        match = re.search(
            r'\b(0[1-9]|1[0-2])/(20\d{2})\b',
            text,
        )

        if match:
            return int(
                match.group(2)
            )

        return None

    # ================================================================
    # HELPERS
    # ================================================================

    @staticmethod
    def _extract_year_from_value(
        value: Any,
    ) -> int | None:

        if value is None:
            return None

        match = re.search(
            r'\b(20[0-3]\d)\b',
            str(value),
        )

        if not match:
            return None

        return int(
            match.group(1)
        )

    @staticmethod
    def _parse_european_number(
        value: str,
    ) -> float | None:

        if not value:
            return None

        text = re.sub(
            r"[^\d\.,]",
            "",
            str(value),
        )

        if not text:
            return None

        if (
            "."
            in text
            and ","
            in text
        ):
            text = (
                text
                .replace(
                    ".",
                    "",
                )
                .replace(
                    ",",
                    ".",
                )
            )

        elif "." in text:

            parts = text.split(
                "."
            )

            if (
                len(parts) == 2
                and len(parts[1]) == 3
            ):
                text = "".join(
                    parts
                )

        elif "," in text:

            parts = text.split(
                ","
            )

            if (
                len(parts) == 2
                and len(parts[1]) == 3
            ):
                text = "".join(
                    parts
                )
            else:
                text = text.replace(
                    ",",
                    ".",
                )

        try:
            return float(
                text
            )
        except ValueError:
            return None

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
    def _normalize_url(
        url: str | None,
    ) -> str | None:

        if not url:
            return None

        url = url.strip()

        if url.startswith(
            "/"
        ):
            url = urljoin(
                AutoScout24Scraper.BASE_URL,
                url,
            )

        # Elimina querystring e fragment.
        url = url.split(
            "?",
            1,
        )[0]

        url = url.split(
            "#",
            1,
        )[0]

        if not AutoScout24Scraper._looks_like_listing_url(
            url
        ):
            return None

        return url

    @staticmethod
    def _looks_like_listing_url(
        url: str,
    ) -> bool:

        if not url:
            return False
    
        try:
            parsed = urlparse(url)
    
            if (
                parsed.netloc
                and "autoscout24.it"
                not in parsed.netloc
            ):
                return False
    
        except Exception:
            return False
    
        path = urlparse(url).path.lower()
    
        return (
            "/annunci/" in path
            or "/offerta/" in path
        )

    @staticmethod
    def _make_listing_id(
        url: str,
    ) -> str:

        return hashlib.sha1(
            url.encode(
                "utf-8"
            )
        ).hexdigest()[:16]

    @staticmethod
    def _is_empty_value(
        value: Any,
    ) -> bool:

        return (
            value is None
            or value == ""
        )

    def _get_visible_text(
        self,
        soup: BeautifulSoup,
    ) -> str:

        # Copia dell'albero per non distruggere
        # eventuali dati usati successivamente.
        for element in soup.find_all(
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

    # ================================================================
    # PAGINAZIONE
    # ================================================================

    def _find_next_page(
        self,
        soup: BeautifulSoup,
        current_url: str,
    ) -> str | None:

        # Cerca link con indicazioni esplicite.
        for link in soup.find_all(
            "a",
            href=True,
        ):

            text = self._clean_text(
                link.get_text(
                    " ",
                    strip=True,
                )
            ).lower()

            aria = str(
                link.get(
                    "aria-label",
                    ""
                )
            ).lower()

            title = str(
                link.get(
                    "title",
                    ""
                )
            ).lower()

            combined = (
                text
                + " "
                + aria
                + " "
                + title
            )

            if (
                "successiv" in combined
                or "next" in combined
            ):

                url = self._normalize_search_url(
                    link.get(
                        "href"
                    )
                )

                if url:
                    return url

        return None

    @staticmethod
    def _normalize_search_url(
        href: str | None,
    ) -> str | None:

        if not href:
            return None

        return urljoin(
            AutoScout24Scraper.BASE_URL,
            href,
        )
