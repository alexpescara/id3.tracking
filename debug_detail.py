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


network_matches = []


def search_recursive(obj, path="root", results=None):
    """
    Cerca ricorsivamente nei dati JSON campi o valori
    interessanti relativi all'equipaggiamento.
    """

    if results is None:
        results = []

    if isinstance(obj, dict):

        for key, value in obj.items():

            key_lower = str(key).lower()

            interesting_key = any(
                term in key_lower
                for term in [
                    "equipment",
                    "equipaggiamento",
                    "optional",
                    "infotainment",
                    "multimedia",
                    "entertainment",
                    "comfort",
                    "safety",
                    "extra",
                ]
            )

            if interesting_key:

                results.append(
                    {
                        "path": f"{path}.{key}",
                        "value": value,
                    }
                )

            search_recursive(
                value,
                f"{path}.{key}",
                results,
            )

    elif isinstance(obj, list):

        for index, value in enumerate(obj):

            search_recursive(
                value,
                f"{path}[{index}]",
                results,
            )

    return results


def handle_response(response):

    try:

        request = response.request

        if request.resource_type not in (
            "xhr",
            "fetch",
        ):
            return

        url = response.url

        # Ci interessa soprattutto GraphQL di AutoScout24.
        if "listing-search-api/graphql" not in url:
            return

        print(
            "\n[GRAPHQL RESPONSE]"
        )

        print(
            "STATUS:",
            response.status,
        )

        print(
            "URL:",
            url,
        )

        try:
            body = response.text()
        except Exception:
            return

        if not body:
            return

        print(
            "BODY SIZE:",
            len(body),
        )

        try:

            data = json.loads(body)

        except Exception as exc:

            print(
                "JSON non valido:",
                repr(exc),
            )

            return

        # --------------------------------------------------------
        # Salviamo la risposta completa
        # --------------------------------------------------------

        network_matches.append(
            {
                "url": url,
                "status": response.status,
                "body": data,
            }
        )

        # --------------------------------------------------------
        # Ricerca testuale
        # --------------------------------------------------------

        serialized = json.dumps(
            data,
            ensure_ascii=False,
        )

        print(
            "\n=== TERMINI NELLA RISPOSTA GRAPHQL ==="
        )

        for term in SEARCH_TERMS:

            count = serialized.lower().count(
                term.lower()
            )

            print(
                f"{term}: {count}"
            )

        # --------------------------------------------------------
        # Ricerca strutturale
        # --------------------------------------------------------

        print(
            "\n=== CAMPI EQUIPMENT / OPTIONAL ==="
        )

        results = search_recursive(data)

        print(
            "Campi interessanti trovati:",
            len(results),
        )

        for item in results:

            print(
                "\nPATH:"
            )

            print(
                item["path"]
            )

            print(
                "VALUE:"
            )

            value = item["value"]

            try:

                print(
                    json.dumps(
                        value,
                        ensure_ascii=False,
                        indent=2,
                    )[:10000]
                )

            except Exception:

                print(
                    repr(value)
                )

    except Exception as exc:

        print(
            "Errore gestione response:",
            repr(exc),
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

    # ============================================================
    # NETWORK LISTENER
    # ============================================================

    page.on(
        "response",
        handle_response,
    )

    # ============================================================
    # APERTURA PAGINA
    # ============================================================

    print(
        "Apro la pagina..."
    )

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    print(
        "Pagina caricata."
    )

    # Aspettiamo le chiamate iniziali.
    page.wait_for_timeout(
        5000
    )

    # ============================================================
    # SCROLL
    # ============================================================

    print(
        "\n=== SCROLL ==="
    )

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

    page.wait_for_timeout(
        5000
    )

    # ============================================================
    # PAGINA
    # ============================================================

    text = page.locator(
        "body"
    ).inner_text()

    html = page.content()

    # ============================================================
    # SALVATAGGIO NETWORK COMPLETO
    # ============================================================

    with open(
        "data/raw/debug_network_full.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            network_matches,
            f,
            ensure_ascii=False,
            indent=2,
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

    # ============================================================
    # NEXT_DATA
    # ============================================================

    soup = BeautifulSoup(
        html,
        "lxml",
    )

    next_script = soup.find(
        "script",
        id="__NEXT_DATA__",
    )

    if next_script and next_script.string:

        try:

            next_data = json.loads(
                next_script.string
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

        except Exception:
            pass

    # ============================================================
    # RIEPILOGO
    # ============================================================

    print(
        "\n"
        + "=" * 70
    )

    print(
        "=== RIEPILOGO ==="
    )

    print(
        "=" * 70
    )

    print(
        "Risposte GraphQL catturate:",
        len(network_matches),
    )

    print(
        "\nFile generati:"
    )

    print(
        "data/raw/debug_network_full.json"
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
        "\nDEBUG COMPLETATO."
    )

    browser.close()
