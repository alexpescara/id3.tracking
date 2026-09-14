from pathlib import Path
import argparse
import yaml
import pandas as pd

from src.scrapers.autoscout24 import AutoScout24Scraper
from src.classifiers.id3 import classify_listing


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    config["scraper"]["headless"] = not args.headed

    source_cfg = config["sources"]["autoscout24"]
    if not source_cfg.get("enabled", True):
        print("AutoScout24 disabilitato.")
        return

    scraper = AutoScout24Scraper(config)
    listings = scraper.search(source_cfg["search_url"])

    classified = [classify_listing(x) for x in listings]
    df = pd.DataFrame(classified)

    out = Path("data/processed/listings.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print(f"Annunci raccolti: {len(df)}")
    print(f"Output: {out}")


if __name__ == "__main__":
    main()
