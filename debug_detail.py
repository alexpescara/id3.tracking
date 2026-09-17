from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json


URL = "https://www.autoscout24.it/annunci/volkswagen-id-3-58-kwh-pro-performance-204cv-elettrica-nero-cat_ma74mo75602-3f34b9ab-81b6-4d5a-8264-5a61a4184ba5"


SEARCH_TERMS = [
    "12,9",
    "12.9",
    "infotainment",
    "display",
    "screen",
    "schermo",
    "touchscreen",
    "ready 2 discover",
    "ready2discover",
    "equipment",
    "equipaggiamento",
    "optional",
    "multimedia",
    "entertainment",
]


def count_and_print(text, keyword):
    count = text.lower().count(keyword.lower())
    print(f"{keyword}: {count}")


with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=True
    )

    page = browser.new_page(
        viewport={
            "width": 1440,
            "height": 2000,
        }
    )

    # ============================================================
    # INTERCETTAZIONE NETWORK
    # ============================================================

    network_matches = []

    def handle_response(response):

        try:
            request = response.request

            resource_type = request.resource_type

            if resource_type not in (
                "xhr",
                "fetch",
            ):
                return

            url = response.url

            # Evitiamo file statici ovvi.
            lower_url = url.lower()

            if any(
                extension in lower_url
                for extension in [
                    ".js",
                    ".css",
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".webp",
                    ".svg",
                    ".woff",
                    ".woff2",
                    ".gif",
                ]
            ):
                return

            content_type = (
                response.headers.get(
                    "content-type",
                    "",
                )
            )

            # Proviamo a leggere solamente le risposte
            # che potrebbero contenere dati.
            try:
                body = response.text()
            except Exception:
                return

            if not body:
                return

            body_lower = body.lower()

            matched_terms = []

            for term in SEARCH_TERMS:
                if term.lower() in body_lower:
                    matched_terms.append(term)

            # Cerchiamo anche URL potenzialmente interessanti.
            url_terms = [
                "equipment",
                "vehicle",
                "detail",
                "listing",
                "offer",
                "advert",
                "vehicledata",
                "vehicle-data",
                "api",
            ]

            interesting_url = any(
                term in lower_url
                for term in url_terms
            )

            if matched_terms or interesting_url:

                network_matches.append(
                    {
                        "url": url,
                        "resource_type": resource_type,
                        "content_type": content_type,
                        "status": response.status,
                        "matched_terms": matched_terms,
                        "body": body,
                    }
                )

        except Exception:
            # Una singola risposta problematica non deve
            # interrompere il debug.
            pass

    page.on(
        "response",
        handle_response,
    )

    # ============================================================
    # APERTURA PAGINA
    # ============================================================

    print("Apro la pagina...")

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    print("Pagina caricata.")

    # Aspettiamo il caricamento iniziale.
    page.wait_for_timeout(5000)

    # ============================================================
    # SCROLL
    # ============================================================

    print("\n=== SCROLL PROGRESSIVO ===")

    for i in range(8):

        print(
            f"Scroll {i + 1}/8"
        )

        page.mouse.wheel(
            0,
            1500,
        )

        page.wait_for_timeout(
            1500
        )

    # Torniamo in cima.
    page.evaluate(
        "window.scrollTo(0, 0)"
    )

    page.wait_for_timeout(3000)

    # ============================================================
    # CONTENUTI PAGINA
    # ============================================================

    text = page.locator(
        "body"
    ).inner_text()

    html = page.content()

    print(
        "\n=== DIMENSIONI PAGINA ==="
    )

    print(
        "Testo visibile:",
        len(text),
        "caratteri",
    )

    print(
        "HTML:",
        len(html),
        "caratteri",
    )

    # ============================================================
    # RICERCA TESTO VISIBILE
    # ============================================================

    print(
        "\n=== RICERCA NEL TESTO VISIBILE ==="
    )

    for keyword in SEARCH_TERMS:
        count_and_print(
            text,
            keyword,
        )

    # ============================================================
    # PARSING HTML
    # ============================================================

    soup = BeautifulSoup(
        html,
        "lxml",
    )

    # ============================================================
    # JSON-LD
    # ============================================================

    print(
        "\n=== JSON-LD ==="
    )

    jsonld_scripts = soup.find_all(
        "script",
        type="application/ld+json",
    )

    print(
        "Blocchi JSON-LD trovati:",
        len(jsonld_scripts),
    )

    # ============================================================
    # NEXT_DATA
    # ============================================================

    print(
        "\n=== NEXT_DATA ==="
    )

    next_script = soup.find(
        "script",
        id="__NEXT_DATA__",
    )

    if next_script and next_script.string:

        print(
            "NEXT_DATA trovato."
        )

        try:

            next_data = json.loads(
                next_script.string
            )

            next_data_text = json.dumps(
                next_data,
                ensure_ascii=False,
            )

            print(
                "Dimensione JSON:",
                len(next_data_text),
                "caratteri",
            )

            for keyword in SEARCH_TERMS:

                count_and_print(
                    next_data_text,
                    keyword,
                )

            with open(
                "data/raw/debug_next_data.json",
                "w",
                encoding="utf-8",
            ) as f:

                json.dump(
                    next_data,
                    f,
                    ensure_ascii=False,
                    indent=2,
                )

        except Exception as exc:

            print(
                "Errore NEXT_DATA:",
                repr(exc),
            )

    else:

        print(
            "NEXT_DATA NON TROVATO."
        )

    # ============================================================
    # RISULTATI NETWORK
    # ============================================================

    print(
        "\n"
        + "=" * 70
    )

    print(
        "=== RISPOSTE NETWORK INTERESSANTI ==="
    )

    print(
        "=" * 70
    )

    print(
        "Risposte trovate:",
        len(network_matches),
    )

    # Salviamo TUTTI i risultati interessanti
    # in un file JSON per poterli analizzare.
    network_output = []

    for index, item in enumerate(
        network_matches,
        start=1,
    ):

        print(
            f"\n--- RESPONSE #{index} ---"
        )

        print(
            "STATUS:",
            item["status"],
        )

        print(
            "TYPE:",
            item["resource_type"],
        )

        print(
            "CONTENT-TYPE:",
            item["content_type"],
        )

        print(
            "URL:",
            item["url"],
        )

        print(
            "TERMINI:",
            item["matched_terms"],
        )

        body = item["body"]

        print(
            "BODY SIZE:",
            len(body),
        )

        # Mostriamo solamente una parte della risposta
        # per evitare un output enorme.
        preview = body[:5000]

        print(
            "\nBODY PREVIEW:"
        )

        print(
            preview
        )

        network_output.append(
            {
                "url": item["url"],
                "resource_type": item[
                    "resource_type"
                ],
                "content_type": item[
                    "content_type"
                ],
                "status": item[
                    "status"
                ],
                "matched_terms": item[
                    "matched_terms"
                ],
                "body": body,
            }
        )

    with open(
        "data/raw/debug_network.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            network_output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(
        "\nSalvato:"
    )

    print(
        "data/raw/debug_network.json"
    )

    # ============================================================
    # SALVATAGGIO PAGINA
    # ============================================================

    with open(
        "data/raw/debug_detail.txt",
        "w",
        encoding="utf-8",
    ) as f:

        f.write(text)

    with open(
        "data/raw/debug_detail.html",
        "w",
        encoding="utf-8",
    ) as f:

        f.write(html)

    print(
        "\n=== FILE GENERATI ==="
    )

    print(
        "data/raw/debug_detail.txt"
    )

    print(
        "data/raw/debug_detail.html"
    )

    print(
        "data/raw/debug_next_data.json"
    )

    print(
        "data/raw/debug_network.json"
    )

    print(
        "\nDEBUG COMPLETATO."
    )

    browser.close()
