from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json


URL = "https://www.autoscout24.it/annunci/volkswagen-id-3-58-kwh-pro-performance-204cv-elettrica-nero-cat_ma74mo75602-3f34b9ab-81b6-4d5a-8264-5a61a4184ba5"


def count_and_print(text, keyword):
    count = text.lower().count(keyword.lower())
    print(f"{keyword}: {count}")


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    page = browser.new_page(
        viewport={
            "width": 1440,
            "height": 2000,
        }
    )

    print("Apro la pagina...")

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    print("Pagina caricata.")

    # Attesa iniziale per permettere al sito di completare
    # il caricamento dei contenuti dinamici.
    page.wait_for_timeout(5000)

    # ============================================================
    # SCROLL PROGRESSIVO
    # ============================================================

    print("\n=== SCROLL PROGRESSIVO ===")

    for i in range(8):
        print(f"Scroll {i + 1}/8")

        page.mouse.wheel(0, 1500)

        page.wait_for_timeout(1500)

    # Torniamo in cima.
    page.evaluate("window.scrollTo(0, 0)")

    page.wait_for_timeout(2000)

    # ============================================================
    # ACQUISIZIONE CONTENUTI
    # ============================================================

    text = page.locator("body").inner_text()

    html = page.content()

    print("\n=== DIMENSIONI PAGINA ===")

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
    # RICERCA NEL TESTO VISIBILE
    # ============================================================

    print("\n=== RICERCA NEL TESTO VISIBILE ===")

    keywords = [
        "12,9",
        "12.9",
        "infotainment",
        "display",
        "schermo",
        "touchscreen",
        "ready 2 discover",
        "ready2discover",
        "equipaggiamento",
        "optional",
    ]

    for keyword in keywords:
        count_and_print(text, keyword)

    # ============================================================
    # CONTESTI 12,9 / INFOTAINMENT NEL TESTO VISIBILE
    # ============================================================

    print("\n=== RICERCA 12,9 / INFOTAINMENT ===")

    search_terms = [
        "12,9",
        "12.9",
        "infotainment",
        "ready 2 discover",
        "ready2discover",
        "touchscreen",
        "equipaggiamento",
        "optional",
    ]

    lower_text = text.lower()

    found_context = False

    for keyword in search_terms:
        start_pos = 0

        while True:
            pos = lower_text.find(
                keyword.lower(),
                start_pos,
            )

            if pos == -1:
                break

            found_context = True

            start = max(
                0,
                pos - 300,
            )

            end = min(
                len(text),
                pos + len(keyword) + 500,
            )

            print(
                f"\n--- {keyword} ---"
            )

            print(
                text[start:end]
            )

            start_pos = pos + len(keyword)

    if not found_context:
        print(
            "Nessun termine interessante trovato "
            "nel testo visibile."
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

    print("\n=== JSON-LD ===")

    jsonld_scripts = soup.find_all(
        "script",
        type="application/ld+json",
    )

    print(
        "Blocchi JSON-LD trovati:",
        len(jsonld_scripts),
    )

    for index, script in enumerate(
        jsonld_scripts,
        start=1,
    ):
        raw = script.string or script.get_text()

        if not raw.strip():
            continue

        print(
            f"\n--- JSON-LD #{index} ---"
        )

        try:
            data = json.loads(raw)

            pretty = json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            )

            print(pretty[:10000])

        except Exception as exc:
            print(
                "Errore parsing JSON-LD:",
                repr(exc),
            )

    # ============================================================
    # NEXT_DATA
    # ============================================================

    print("\n=== RICERCA NEXT_DATA ===")

    next_script = soup.find(
        "script",
        id="__NEXT_DATA__",
    )

    next_data_text = ""

    if next_script and next_script.string:

        print("NEXT_DATA trovato.")

        raw_next_data = next_script.string

        print(
            "Dimensione JSON:",
            len(raw_next_data),
            "caratteri",
        )

        try:
            next_data = json.loads(
                raw_next_data
            )

            # Salviamo il NEXT_DATA completo.
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

            print(
                "Salvato: "
                "data/raw/debug_next_data.json"
            )

            next_data_text = json.dumps(
                next_data,
                ensure_ascii=False,
            )

            # ----------------------------------------------------
            # Ricerca termini
            # ----------------------------------------------------

            print(
                "\n=== RICERCA TERMINI NEL NEXT_DATA ==="
            )

            next_keywords = [
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
                "comfort",
                "technology",
                "tech",
            ]

            for keyword in next_keywords:
                count_and_print(
                    next_data_text,
                    keyword,
                )

            # ----------------------------------------------------
            # Contesti interessanti
            # ----------------------------------------------------

            print(
                "\n=== CONTESTI INTERESSANTI NEXT_DATA ==="
            )

            lower_next_data = (
                next_data_text.lower()
            )

            context_keywords = [
                "12,9",
                "12.9",
                "infotainment",
                "ready 2 discover",
                "ready2discover",
                "equipment",
                "equipaggiamento",
            ]

            found_next_context = False

            for keyword in context_keywords:

                start_pos = 0

                while True:

                    pos = lower_next_data.find(
                        keyword.lower(),
                        start_pos,
                    )

                    if pos == -1:
                        break

                    found_next_context = True

                    start = max(
                        0,
                        pos - 500,
                    )

                    end = min(
                        len(next_data_text),
                        pos + len(keyword) + 1000,
                    )

                    print(
                        f"\n--- {keyword} ---"
                    )

                    print(
                        next_data_text[start:end]
                    )

                    start_pos = (
                        pos + len(keyword)
                    )

            if not found_next_context:
                print(
                    "Nessun termine interessante "
                    "trovato nel NEXT_DATA."
                )

        except Exception as exc:

            print(
                "Errore parsing NEXT_DATA:",
                repr(exc),
            )

    else:

        print(
            "NEXT_DATA NON TROVATO."
        )

    # ============================================================
    # SALVATAGGIO TESTO E HTML
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

    print("\n=== FILE GENERATI ===")

    print(
        "data/raw/debug_detail.txt"
    )

    print(
        "data/raw/debug_detail.html"
    )

    if next_data_text:
        print(
            "data/raw/debug_next_data.json"
        )

    print("\nDEBUG COMPLETATO.")

    browser.close()
