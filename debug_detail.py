import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


URL = (
    "https://www.autoscout24.it/annunci/"
    "volkswagen-id-3-58-kwh-pro-performance-204cv-elettrica-nero-"
    "cat_ma74mo75602-3f34b9ab-81b6-4d5a-8264-5a61a4184ba5"
)

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

OUTPUT_DIR = Path("data/raw")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

graphql_requests = []
graphql_responses = []


# ============================================================
# FUNZIONI UTILI
# ============================================================

def print_separator():
    print()
    print("=" * 70)


def search_text(text, label):
    print()
    print(f"=== RICERCA TERMINI IN {label} ===")

    if not text:
        print("Testo vuoto.")
        return

    lower = text.lower()

    for term in SEARCH_TERMS:
        count = lower.count(term.lower())
        print(f"{term}: {count}")


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def get_visible_text(page):
    try:
        return clean_text(page.locator("body").inner_text())
    except Exception as exc:
        print(f"Errore lettura body: {exc}")
        return ""


# ============================================================
# RICERCA RICORSIVA DEI CAMPI INTERESSANTI
# ============================================================

INTERESTING_KEYS = [
    "equipment",
    "equipaggiamento",
    "optional",
    "infotainment",
    "multimedia",
    "entertainment",
    "comfort",
    "safety",
    "extra",
    "feature",
    "features",
    "option",
    "options",
]


def search_recursive(obj, path="root", results=None):
    if results is None:
        results = []

    if isinstance(obj, dict):
        for key, value in obj.items():

            key_lower = str(key).lower()

            if any(term in key_lower for term in INTERESTING_KEYS):
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
        for index, item in enumerate(obj):
            search_recursive(
                item,
                f"{path}[{index}]",
                results,
            )

    return results


# ============================================================
# GRAPHQL REQUEST
# ============================================================

def handle_request(request):
    url = request.url

    if "listing-search-api/graphql" not in url:
        return

    print()
    print("[GRAPHQL REQUEST]")
    print(f"METHOD: {request.method}")
    print(f"URL: {url}")

    try:
        post_data = request.post_data

        if not post_data:
            print("POST DATA: vuoto")
            return

        print(f"POST BODY SIZE: {len(post_data)}")

        data = None

        try:
            data = json.loads(post_data)
        except Exception:
            print("POST BODY non è JSON valido.")
            print("PREVIEW:")
            print(post_data[:2000])

        request_entry = {
            "url": url,
            "method": request.method,
            "headers": dict(request.headers),
            "raw_post_data": post_data,
            "json": data,
        }

        graphql_requests.append(request_entry)

        if isinstance(data, dict):

            print()
            print("--- GRAPHQL REQUEST DETAILS ---")

            operation_name = data.get("operationName")

            print(f"operationName: {operation_name}")

            query = data.get("query")

            if query:
                print()
                print("QUERY GRAPHQL:")
                print("-" * 70)
                print(query)
                print("-" * 70)

            variables = data.get("variables")

            if variables is not None:
                print()
                print("VARIABLES:")
                print(json.dumps(
                    variables,
                    ensure_ascii=False,
                    indent=2,
                ))

    except Exception as exc:
        print(f"Errore intercettazione GraphQL request: {exc}")


# ============================================================
# GRAPHQL RESPONSE
# ============================================================

def handle_response(response):
    url = response.url

    if "listing-search-api/graphql" not in url:
        return

    print()
    print("[GRAPHQL RESPONSE]")
    print(f"STATUS: {response.status}")
    print(f"URL: {url}")

    try:
        body = response.text()

        print(f"BODY SIZE: {len(body)}")

        data = json.loads(body)

        entry = {
            "url": url,
            "status": response.status,
            "headers": dict(response.headers),
            "body": data,
        }

        graphql_responses.append(entry)

        search_text(
            body,
            "RISPOSTA GRAPHQL COMPLETA",
        )

        print()
        print("=== CAMPI EQUIPMENT / OPTIONAL ===")

        results = search_recursive(data)

        print(f"Campi interessanti trovati: {len(results)}")

        for item in results:
            print()
            print(f"PATH: {item['path']}")

            try:
                print(
                    json.dumps(
                        item["value"],
                        ensure_ascii=False,
                        indent=2,
                    )[:10000]
                )
            except Exception:
                print(str(item["value"])[:10000])

    except Exception as exc:
        print(f"Errore lettura risposta GraphQL: {exc}")


# ============================================================
# MAIN
# ============================================================

def main():

    print_separator()
    print("DEBUG AUTOSCOUT24")
    print_separator()

    print(f"URL:")
    print(URL)

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            viewport={
                "width": 1440,
                "height": 1000,
            }
        )

        # ----------------------------------------------------
        # INTERCETTAZIONE NETWORK
        # ----------------------------------------------------

        page.on(
            "request",
            handle_request,
        )

        page.on(
            "response",
            handle_response,
        )

        # ----------------------------------------------------
        # APERTURA PAGINA
        # ----------------------------------------------------

        print_separator()
        print("=== APERTURA PAGINA ===")
        print_separator()

        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(5000)

        # ----------------------------------------------------
        # SCROLL
        # ----------------------------------------------------

        print_separator()
        print("=== SCROLL ===")
        print_separator()

        for i in range(8):

            print(f"Scroll {i + 1}/8")

            page.mouse.wheel(
                0,
                1500,
            )

            page.wait_for_timeout(1500)

        # ----------------------------------------------------
        # TESTO VISIBILE
        # ----------------------------------------------------

        visible_text = get_visible_text(page)

        print_separator()
        print("=== TESTO VISIBILE ===")
        print_separator()

        print(
            f"Dimensione testo visibile: "
            f"{len(visible_text)} caratteri"
        )

        search_text(
            visible_text,
            "TESTO VISIBILE",
        )

        # ----------------------------------------------------
        # HTML
        # ----------------------------------------------------

        html = page.content()

        print_separator()
        print("=== HTML ===")
        print_separator()

        print(
            f"Dimensione HTML: "
            f"{len(html)} caratteri"
        )

        search_text(
            html,
            "HTML COMPLETO",
        )

        # ----------------------------------------------------
        # JSON-LD
        # ----------------------------------------------------

        print_separator()
        print("=== JSON-LD ===")
        print_separator()

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        json_ld_objects = []

        for script in soup.find_all(
            "script",
            type="application/ld+json",
        ):

            try:

                data = json.loads(
                    script.string or script.get_text()
                )

                json_ld_objects.append(data)

            except Exception:
                pass

        print(
            f"JSON-LD trovati: "
            f"{len(json_ld_objects)}"
        )

        json_ld_text = json.dumps(
            json_ld_objects,
            ensure_ascii=False,
            indent=2,
        )

        search_text(
            json_ld_text,
            "JSON-LD",
        )

        # ----------------------------------------------------
        # NEXT_DATA
        # ----------------------------------------------------

        print_separator()
        print("=== NEXT_DATA ===")
        print_separator()

        next_data = None

        script = soup.find(
            "script",
            id="__NEXT_DATA__",
        )

        if script:

            try:

                next_data = json.loads(
                    script.string or script.get_text()
                )

                print("NEXT_DATA trovato.")

                next_data_text = json.dumps(
                    next_data,
                    ensure_ascii=False,
                    indent=2,
                )

                print(
                    f"Dimensione JSON: "
                    f"{len(next_data_text)} caratteri"
                )

                search_text(
                    next_data_text,
                    "NEXT_DATA",
                )

                next_results = search_recursive(
                    next_data
                )

                print()
                print(
                    "=== CAMPI INTERESSANTI NEXT_DATA ==="
                )

                print(
                    f"Campi trovati: "
                    f"{len(next_results)}"
                )

                for item in next_results:

                    print()
                    print(
                        f"PATH: {item['path']}"
                    )

                    try:
                        print(
                            json.dumps(
                                item["value"],
                                ensure_ascii=False,
                                indent=2,
                            )[:5000]
                        )
                    except Exception:
                        print(
                            str(item["value"])[:5000]
                        )

                with open(
                    OUTPUT_DIR / "debug_next_data.json",
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
                    f"Errore parsing NEXT_DATA: "
                    f"{exc}"
                )

        else:

            print("NEXT_DATA NON trovato.")

        # ----------------------------------------------------
        # SALVATAGGIO HTML
        # ----------------------------------------------------

        with open(
            OUTPUT_DIR / "debug_detail.html",
            "w",
            encoding="utf-8",
        ) as f:

            f.write(html)

        # ----------------------------------------------------
        # SALVATAGGIO TESTO
        # ----------------------------------------------------

        with open(
            OUTPUT_DIR / "debug_detail.txt",
            "w",
            encoding="utf-8",
        ) as f:

            f.write(visible_text)

        # ----------------------------------------------------
        # SALVATAGGIO GRAPHQL REQUEST
        # ----------------------------------------------------

        print_separator()
        print("=== SALVATAGGIO GRAPHQL REQUEST ===")
        print_separator()

        requests_path = (
            OUTPUT_DIR
            / "debug_graphql_requests.json"
        )

        with open(
            requests_path,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                graphql_requests,
                f,
                ensure_ascii=False,
                indent=2,
            )

        print(
            f"Richieste GraphQL salvate: "
            f"{len(graphql_requests)}"
        )

        print(
            f"File: {requests_path}"
        )

        # ----------------------------------------------------
        # SALVATAGGIO GRAPHQL RESPONSE
        # ----------------------------------------------------

        print_separator()
        print("=== SALVATAGGIO GRAPHQL RESPONSE ===")
        print_separator()

        responses_path = (
            OUTPUT_DIR
            / "debug_network_full.json"
        )

        with open(
            responses_path,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                graphql_responses,
                f,
                ensure_ascii=False,
                indent=2,
            )

        print(
            f"Risposte GraphQL salvate: "
            f"{len(graphql_responses)}"
        )

        print(
            f"File: {responses_path}"
        )

        # ----------------------------------------------------
        # RIEPILOGO
        # ----------------------------------------------------

        print_separator()
        print("=== RIEPILOGO ===")
        print_separator()

        print(
            f"Richieste GraphQL catturate: "
            f"{len(graphql_requests)}"
        )

        print(
            f"Risposte GraphQL catturate: "
            f"{len(graphql_responses)}"
        )

        print()
        print("File generati:")

        print(
            "data/raw/debug_graphql_requests.json"
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

        print()
        print("DEBUG COMPLETATO.")

        browser.close()


if __name__ == "__main__":
    main()
