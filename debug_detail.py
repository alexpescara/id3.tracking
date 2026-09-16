from playwright.sync_api import sync_playwright

URL = "https://www.autoscout24.it/annunci/volkswagen-id-3-58-kwh-pro-performance-204cv-elettrica-nero-cat_ma74mo75602-3f34b9ab-81b6-4d5a-8264-5a61a4184ba5"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    page = browser.new_page(
        viewport={"width": 1440, "height": 2000}
    )

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(5000)

    text = page.locator("body").inner_text()

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
        f.write(page.content())

    print("DEBUG GENERATO")
    print("Testo:", len(text), "caratteri")
    print("HTML:", len(page.content()), "caratteri")

    browser.close()
