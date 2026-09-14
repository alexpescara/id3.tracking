import json
import re
import time
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from .base import BaseScraper


PRICE_RE = re.compile(r"(\d[\d\.\s]*)\s*€")
KM_RE = re.compile(r"(\d[\d\.\s]*)\s*km", re.I)
YEAR_RE = re.compile(r"\b(20\d{2})\b")
BATTERY_RE = re.compile(r"\b(5[89]|6[0-9]|7[0-9])\s*kWh\b", re.I)
POWER_RE = re.compile(r"\b(\d{2,3})\s*(?:CV|PS)\b", re.I)


class AutoScout24Scraper(BaseScraper):
    """
    Conservative public-page scraper.

    It does not bypass authentication, CAPTCHA, robots restrictions or
    anti-bot mechanisms. If a page cannot be accessed normally, it is skipped.
    """

    def search(self, search_url: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        s_cfg = self.config["scraper"]

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=s_cfg.get("headless", True))
            context = browser.new_context(
                user_agent=s_cfg.get("user_agent"),
                locale="it-IT",
                viewport={"width": 1440, "height": 1000},
            )
            page = context.new_page()
            page.set_default_timeout(s_cfg.get("timeout_ms", 30000))

            try:
                page.goto(search_url, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                self._dismiss_common_consent(page)

                max_pages = int(s_cfg.get("max_pages", 1))
                for page_no in range(max_pages):
                    html = page.content()
                    results.extend(self._parse_search_page(html, page.url))

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

                    from urllib.parse import urljoin
                    next_url = urljoin(page.url, href)
                    time.sleep(float(s_cfg.get("delay_seconds", 2.5)))
                    page.goto(next_url, wait_until="domcontentloaded")
                    page.wait_for_timeout(1800)

            finally:
                context.close()
                browser.close()

        return self._deduplicate(results)

    @staticmethod
    def _dismiss_common_consent(page) -> None:
        selectors = [
            'button:has-text("Accetta")',
            'button:has-text("Accetta tutto")',
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

    def _parse_search_page(self, html: str, source_url: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        cards = []

        # Prefer JSON-LD because it is less dependent on CSS class names.
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except Exception:
                continue
            candidates = data if isinstance(data, list) else [data]
            for obj in candidates:
                if isinstance(obj, dict) and obj.get("@type") in {
                    "Car", "Vehicle", "Product"
                }:
                    cards.append(self._from_jsonld(obj, source_url))

        # Fallback: collect links that look like vehicle detail pages.
        if not cards:
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                text = " ".join(a.stripped_strings)
                if "/annunci/" not in href or "id.3" not in text.lower():
                    continue
                cards.append(self._from_text(text, href, source_url))

        return [x for x in cards if x.get("url")]

    def _from_jsonld(self, obj: dict, source_url: str) -> dict:
        offers = obj.get("offers") or {}
        url = obj.get("url") or source_url
        description = obj.get("description") or ""
        title = obj.get("name") or "Volkswagen ID.3"

        return self._normalise(
            {
                "url": url,
                "title": title,
                "description": description,
                "price_raw": offers.get("price"),
                "mileage_raw": self._jsonld_mileage(obj),
                "year_raw": self._jsonld_year(obj),
                "raw": json.dumps(obj, ensure_ascii=False),
            }
        )

    @staticmethod
    def _jsonld_mileage(obj: dict):
        mileage = obj.get("mileageFromOdometer")
        if isinstance(mileage, dict):
            return mileage.get("value")
        return mileage

    @staticmethod
    def _jsonld_year(obj: dict):
        year = obj.get("vehicleModelDate") or obj.get("productionDate")
        return year

    def _from_text(self, text: str, href: str, source_url: str) -> dict:
        return self._normalise(
            {
                "url": href,
                "title": text[:200],
                "description": text,
                "price_raw": None,
                "mileage_raw": None,
                "year_raw": None,
                "raw": text,
            }
        )

    def _normalise(self, item: dict) -> dict:
        raw = item.get("raw", "")
        title = item.get("title", "")
        description = item.get("description", "")
        combined = f"{title} {description} {raw}"

        price = self._number(item.get("price_raw"))
        mileage = self._number(item.get("mileage_raw"))

        if price is None:
            m = PRICE_RE.search(combined)
            price = self._number(m.group(1)) if m else None

        if mileage is None:
            m = KM_RE.search(combined)
            mileage = self._number(m.group(1)) if m else None

        year = self._number(item.get("year_raw"))
        if year is None:
            m = YEAR_RE.search(combined)
            year = int(m.group(1)) if m else None

        battery = None
        m = BATTERY_RE.search(combined)
        if m:
            battery = float(m.group(1))

        power = None
        m = POWER_RE.search(combined)
        if m:
            power = int(m.group(1))

        return {
            "listing_id": self._listing_id(item.get("url", "")),
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
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _number(value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return value
        s = str(value).replace(".", "").replace(" ", "").replace(",", ".")
        m = re.search(r"\d+(?:\.\d+)?", s)
        return float(m.group()) if m else None

    @staticmethod
    def _listing_id(url: str) -> str:
        import hashlib
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _deduplicate(items):
        unique = {}
        for item in items:
            unique[item["listing_id"]] = item
        return list(unique.values())
