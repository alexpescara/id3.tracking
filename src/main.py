from pathlib import Path
import argparse

import pandas as pd
import yaml

from src.scrapers.autoscout24 import AutoScout24Scraper
from src.classifiers.id3 import classify_listing


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def apply_filters(
    df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """
    Applica i filtri configurati alla fine dello scraping.

    Filtri attuali:
    - anno >= min_year
    - batteria >= min_battery_kwh
    - prezzo <= max_price_eur
    """

    filters = config.get("filters", {})

    min_year = filters.get("min_year")
    min_battery_kwh = filters.get("min_battery_kwh")
    max_price_eur = filters.get("max_price_eur")

    if df.empty:
        return df

    # Conversione robusta dei campi numerici
    for column in [
        "price_eur",
        "mileage_km",
        "registration_year",
        "battery_kwh",
        "power_hp",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

    before = len(df)

    if min_year is not None:
        df = df[
            df["registration_year"].notna()
            & (df["registration_year"] >= min_year)
        ]

    if min_battery_kwh is not None:
        df = df[
            df["battery_kwh"].notna()
            & (df["battery_kwh"] >= min_battery_kwh)
        ]

    if max_price_eur is not None:
        df = df[
            df["price_eur"].notna()
            & (df["price_eur"] <= max_price_eur)
        ]

    after = len(df)

    print(
        "Filtro annunci:"
        f" {before} -> {after}"
    )

    if min_year is not None:
        print(
            f"  Anno minimo: {min_year}"
        )

    if min_battery_kwh is not None:
        print(
            f"  Batteria minima: "
            f"{min_battery_kwh} kWh"
        )

    if max_price_eur is not None:
        print(
            f"  Prezzo massimo: "
            f"{max_price_eur} €"
        )

    return df.reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config",
        default="config.yaml",
    )

    parser.add_argument(
        "--headed",
        action="store_true",
    )

    args = parser.parse_args()

    config = load_config(
        args.config
    )

    config["scraper"]["headless"] = not args.headed

    source_cfg = config[
        "sources"
    ]["autoscout24"]

    if not source_cfg.get(
        "enabled",
        True,
    ):
        print(
            "AutoScout24 disabilitato."
        )
        return

    # ------------------------------------------------------------
    # SCRAPING
    # ------------------------------------------------------------

    scraper = AutoScout24Scraper(
        config
    )

    listings = scraper.search(
        source_cfg["search_url"]
    )

    print(
        f"Annunci raccolti dallo scraper: "
        f"{len(listings)}"
    )

    if not listings:
        print(
            "Nessun annuncio raccolto."
        )
        return

    # ------------------------------------------------------------
    # CLASSIFICAZIONE
    # ------------------------------------------------------------

    classified = [
        classify_listing(item)
        for item in listings
    ]

    for item in classified:
        item.setdefault(
            "equipment",
            "",
        )

    df = pd.DataFrame(
        classified
    )

    # ------------------------------------------------------------
    # FILTRI
    # ------------------------------------------------------------

    df = apply_filters(
        df,
        config,
    )

    # ------------------------------------------------------------
    # OUTPUT
    # ------------------------------------------------------------

    out = Path(
        "data/processed/listings.csv"
    )

    out.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    df.to_csv(
        out,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        f"Annunci finali: {len(df)}"
    )

    print(
        f"Output: {out}"
    )

    if not df.empty:
        print()
        print(
            "Annunci filtrati:"
        )

        columns = [
            "title",
            "price_eur",
            "mileage_km",
            "registration_year",
            "battery_kwh",
            "power_hp",
            "seller",
            "equipment",
            "infotainment_129_candidate",
            "confidence_score",
            "classification_evidence",
        ]

        available_columns = [
            column
            for column in columns
            if column in df.columns
        ]

        print(
            df[
                available_columns
            ].to_string(
                index=False
            )
        )


if __name__ == "__main__":
    main()
