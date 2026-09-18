import json
from pathlib import Path

from playwright.sync_api import sync_playwright


URL = (
    "https://www.autoscout24.it/annunci/"
    "volkswagen-id-3-58-kwh-pro-performance-204cv-elettrica-nero-"
    "cat_ma74mo75602-3f34b9ab-81b6-4d5a-8264-5a61a4184ba5"
)

OUTPUT_DIR = Path("data/raw")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# Parole che ci interessano nelle QUERY GraphQL.
# Non cerchiamo queste parole nelle risposte:
# vogliamo sapere quali CAMPI il browser sta chiedendo.
INTERESTING_TERMS = [
    "detail",
    "details",
    "vehicle",
    "attribute",
    "attributes",
    "feature",
    "features",
    "equipment",
    "equipments",
    "option",
    "options",
    "specification",
    "specifications",
    "description",
    "media",
    "comfort",
    "technology",
    "entertainment",
]


graphql_requests = []


def is_interesting_query(query):
    """
    Restituisce i termini trovati nella query GraphQL.
    """
    if not query:
        return []

    query_lower = query.lower()

    return [
        term
        for term in INTERESTING_TERMS
        if term.lower() in query_lower
    ]


def handle_request(request):
    """
    Intercetta tutte le richieste verso l'endpoint GraphQL
    di AutoScout24.
    """

    if "listing-search-api/graphql" not in request.url:
        return

    if request.method.upper() != "POST":
        return

    try:
        post_data = request.post_data

        if not post_data:
            return

        try:
            data = json.loads(post_data)
        except json.JSONDecodeError:
            print()
            print("[GRAPHQL REQUEST - JSON NON VALIDO]")
            print(request.url)
            return

        operation_name = data.get("operationName")
        query = data.get("query")
        variables = data.get("variables")

        interesting_terms = is_interesting_query(query)

        entry = {
            "url": request.url,
            "method": request.method,
            "operationName": operation_name,
            "query": query,
            "variables": variables,
            "interesting_terms": interesting_terms,
        }

        graphql_requests.append(entry)

        print()
        print("=" * 70)
        print("GRAPHQL REQUEST")
        print("=" * 70)

        print(f"Operation: {operation_name}")
        print(f"Query size: {len(query or '')}")
        print(
            "Termini interessanti: "
            + (
                ", ".join(interesting_terms)
                if interesting_terms
                else "nessuno"
            )
        )

        # Stampiamo sempre l'operationName.
        # La query completa viene stampata soltanto se
        # contiene almeno uno dei termini interessanti.
        if interesting_terms:

            print()
            print("--- QUERY INTERESSANTE ---")
            print("-" * 70)
            print(query)
            print("-" * 70)

            if variables is not None:
                print()
                print("--- VARIABLES ---")
                print(
                    json.dumps(
                        variables,
                        ensure_ascii=False,
                        indent=2,
                    )
                )

    except Exception as exc:
        print(
            f"Errore durante intercettazione "
            f"GraphQL request: {exc}"
        )


def save_requests():
    """
    Salva tutte le richieste GraphQL catturate.
    """

    output_file = (
        OUTPUT_DIR / "debug_graphql_requests.json"
    )

    with open(
        output_file,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            graphql_requests,
            f,
            ensure_ascii=False,
            indent=2,
        )

    return output_file


def main():

    print("=" * 70)
    print("DEBUG GRAPHQL AUTOSCOUT24")
    print("=" * 70)

    print()
    print("URL analizzato:")
    print(URL)

    print()
    print(
        "Il debug intercetterà tutte le richieste POST "
        "verso listing-search-api/graphql."
    )

    print()
    print(
        "Verranno evidenziate le query che contengono "
        "campi potenzialmente relativi a dettagli/equipaggiamento."
    )

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

        # ====================================================
        # NETWORK
        # ====================================================

        page.on(
            "request",
            handle_request,
        )

        # ====================================================
        # APERTURA PAGINA
        # ====================================================

        print()
        print("=" * 70)
        print("APERTURA PAGINA")
        print("=" * 70)

        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        # Lasciamo alla pagina il tempo di eseguire
        # le chiamate GraphQL iniziali.
        page.wait_for_timeout(6000)

        # ====================================================
        # SCROLL
        # ====================================================

        print()
        print("=" * 70)
        print("SCROLL")
        print("=" * 70)

        for i in range(8):

            print(
                f"Scroll {i + 1}/8"
            )

            page.mouse.wheel(
                0,
                1500,
            )

            page.wait_for_timeout(1500)

        # ====================================================
        # ULTERIORE ATTESA
        # ====================================================

        page.wait_for_timeout(3000)

        # ====================================================
        # SALVATAGGIO
        # ====================================================

        output_file = save_requests()

        # ====================================================
        # RIEPILOGO
        # ====================================================

        print()
        print("=" * 70)
        print("RIEPILOGO")
        print("=" * 70)

        print(
            f"Richieste GraphQL catturate: "
            f"{len(graphql_requests)}"
        )

        print()
        print(
            f"File generato:\n"
            f"{output_file}"
        )

        print()

        # Elenco sintetico delle operation trovate.
        print("--- OPERATION NAME TROVATI ---")

        operation_names = []

        for request in graphql_requests:

            operation_name = request.get(
                "operationName"
            )

            if operation_name not in operation_names:
                operation_names.append(
                    operation_name
                )

        if operation_names:

            for operation_name in operation_names:
                print(
                    f"- {operation_name}"
                )

        else:

            print(
                "Nessuna operation GraphQL trovata."
            )

        # ====================================================
        # QUERY INTERESSANTI
        # ====================================================

        print()
        print("--- QUERY CON CAMPI INTERESSANTI ---")

        interesting_requests = [
            request
            for request in graphql_requests
            if request.get("interesting_terms")
        ]

        print(
            f"Query interessanti: "
            f"{len(interesting_requests)}"
        )

        for index, request in enumerate(
            interesting_requests,
            start=1,
        ):

            print()
            print(
                f"[QUERY INTERESSANTE #{index}]"
            )

            print(
                f"Operation: "
                f"{request.get('operationName')}"
            )

            print(
                "Termini: "
                + ", ".join(
                    request.get(
                        "interesting_terms",
                        [],
                    )
                )
            )

        print()
        print("DEBUG COMPLETATO.")

        browser.close()


if __name__ == "__main__":
    main()
