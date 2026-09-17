from playwright.sync_api import sync_playwright


URL = (
    "https://www.autoscout24.it/annunci/"
    "volkswagen-id-3-58-kwh-pro-performance-204cv-"
    "elettrica-nero-cat_ma74mo75602-"
    "3f34b9ab-81b6-4d5a-8264-5a61a4184ba5"
)


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

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    print("Pagina caricata")

    # Attesa iniziale
    page.wait_for_timeout(5000)

    # ---------------------------------------------------------
    # Scroll progressivo
    # ---------------------------------------------------------

    for i in range(8):
        print(
            f"Scroll {i + 1}/8"
        )

        page.evaluate(
            """
            () => {
                window.scrollBy(
                    0,
                    Math.max(
                        800,
                        window.innerHeight * 0.8
                    )
                );
            }
            """
        )

        page.wait_for_timeout(1500)

    # Torniamo in cima
    page.evaluate(
        "() => window.scrollTo(0, 0)"
    )

    page.wait_for_timeout(2000)

    # ---------------------------------------------------------
    # Testo visibile
    # ---------------------------------------------------------

    text = page.locator(
        "body"
    ).inner_text()

    # ---------------------------------------------------------
    # HTML finale
    # ---------------------------------------------------------

    html = page.content()

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

    print()
    print(
        "DEBUG GENERATO"
    )

    print(
        "Testo:",
        len(text),
        "caratteri",
    )

    print(
        "HTML:",
        len(html),
        "caratteri",
    )

    # ---------------------------------------------------------
    # Ricerca diretta nel testo visibile
    # ---------------------------------------------------------

    print()
    print(
        "=== RICERCA NEL TESTO VISIBILE ==="
    )

    keywords = [
        "12,9",
        "12.9",
        "infotainment",
        "display",
        "schermo",
        "touchscreen",
        "ready 2 discover",
        "equipaggiamento",
        "optional",
    ]

    text_lower = text.lower()

    for keyword in keywords:
        print(
            f"{keyword}: "
            f"{text_lower.count(keyword.lower())}"
        )

    browser.close()
