from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class TrackingRepository:
    """SQLite repository for listings and historical observations."""

    def __init__(
        self,
        db_path: str | Path = "data/id3_tracking.db",
        timezone: str = "Europe/Rome",
    ) -> None:
        self.db_path = Path(db_path)
        self.timezone = timezone

        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS listings (
                    listing_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT,
                    price_eur REAL,
                    mileage_km INTEGER,
                    registration_year INTEGER,
                    battery_kwh REAL,
                    power_hp REAL,
                    seller TEXT,
                    description TEXT,
                    equipment TEXT,
                    restyling_candidate INTEGER,
                    infotainment_129_candidate INTEGER,
                    confidence_score INTEGER,
                    classification_evidence TEXT,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS listing_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    price_eur REAL,
                    mileage_km INTEGER,
                    registration_year INTEGER,
                    battery_kwh REAL,
                    power_hp REAL,
                    title TEXT,
                    seller TEXT,
                    FOREIGN KEY (listing_id)
                        REFERENCES listings(listing_id)
                        ON DELETE CASCADE,
                    UNIQUE (listing_id, observed_at)
                );

                CREATE INDEX IF NOT EXISTS idx_listings_last_seen
                    ON listings(last_seen);

                CREATE INDEX IF NOT EXISTS idx_listings_status
                    ON listings(status);

                CREATE INDEX IF NOT EXISTS idx_snapshots_listing
                    ON listing_snapshots(listing_id, observed_at);
                """
            )

    def _now(self) -> str:
        try:
            tz = ZoneInfo(self.timezone)
        except Exception:
            tz = ZoneInfo("UTC")
        return datetime.now(tz).isoformat(timespec="seconds")

    @staticmethod
    def _bool_to_int(value: bool | None) -> int | None:
        if value is None:
            return None
        return 1 if value else 0

    def save_listing(
        self,
        listing: dict,
        source: str = "autoscout24",
        observed_at: str | None = None,
    ) -> None:
        """Upsert the current listing and append one historical snapshot."""
        listing_id = listing.get("listing_id")
        url = listing.get("url")

        if not listing_id:
            raise ValueError("listing_id mancante")
        if not url:
            raise ValueError(f"url mancante per listing_id={listing_id}")

        observed_at = observed_at or self._now()

        values = {
            "listing_id": str(listing_id),
            "source": source,
            "url": str(url),
            "title": listing.get("title"),
            "price_eur": listing.get("price_eur"),
            "mileage_km": listing.get("mileage_km"),
            "registration_year": listing.get("registration_year"),
            "battery_kwh": listing.get("battery_kwh"),
            "power_hp": listing.get("power_hp"),
            "seller": listing.get("seller"),
            "description": listing.get("description"),
            "equipment": listing.get("equipment"),
            "restyling_candidate": self._bool_to_int(
                listing.get("restyling_candidate")
            ),
            "infotainment_129_candidate": self._bool_to_int(
                listing.get("infotainment_129_candidate")
            ),
            "confidence_score": listing.get("confidence_score"),
            "classification_evidence": listing.get(
                "classification_evidence"
            ),
            "first_seen": observed_at,
            "last_seen": observed_at,
            "status": "active",
            "created_at": observed_at,
            "updated_at": observed_at,
        }

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT first_seen FROM listings WHERE listing_id = ?",
                (values["listing_id"],),
            ).fetchone()

            if existing:
                values["first_seen"] = existing["first_seen"]

            connection.execute(
                """
                INSERT INTO listings (
                    listing_id, source, url, title, price_eur,
                    mileage_km, registration_year, battery_kwh,
                    power_hp, seller, description, equipment,
                    restyling_candidate, infotainment_129_candidate,
                    confidence_score, classification_evidence,
                    first_seen, last_seen, status,
                    created_at, updated_at
                )
                VALUES (
                    :listing_id, :source, :url, :title, :price_eur,
                    :mileage_km, :registration_year, :battery_kwh,
                    :power_hp, :seller, :description, :equipment,
                    :restyling_candidate, :infotainment_129_candidate,
                    :confidence_score, :classification_evidence,
                    :first_seen, :last_seen, :status,
                    :created_at, :updated_at
                )
                ON CONFLICT(listing_id) DO UPDATE SET
                    source = excluded.source,
                    url = excluded.url,
                    title = excluded.title,
                    price_eur = excluded.price_eur,
                    mileage_km = excluded.mileage_km,
                    registration_year = excluded.registration_year,
                    battery_kwh = excluded.battery_kwh,
                    power_hp = excluded.power_hp,
                    seller = excluded.seller,
                    description = excluded.description,
                    equipment = excluded.equipment,
                    restyling_candidate = excluded.restyling_candidate,
                    infotainment_129_candidate =
                        excluded.infotainment_129_candidate,
                    confidence_score = excluded.confidence_score,
                    classification_evidence =
                        excluded.classification_evidence,
                    last_seen = excluded.last_seen,
                    status = 'active',
                    updated_at = excluded.updated_at
                """,
                values,
            )

            connection.execute(
                """
                INSERT OR IGNORE INTO listing_snapshots (
                    listing_id, observed_at, price_eur,
                    mileage_km, registration_year, battery_kwh,
                    power_hp, title, seller
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["listing_id"],
                    observed_at,
                    values["price_eur"],
                    values["mileage_km"],
                    values["registration_year"],
                    values["battery_kwh"],
                    values["power_hp"],
                    values["title"],
                    values["seller"],
                ),
            )

    def save_listings(
        self,
        listings: list[dict],
        source: str = "autoscout24",
    ) -> int:
        """Save a batch using one timestamp for the whole scraping run."""
        observed_at = self._now()

        for listing in listings:
            self.save_listing(
                listing,
                source=source,
                observed_at=observed_at,
            )

        return len(listings)

    def get_listing(self, listing_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM listings WHERE listing_id = ?",
                (listing_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_history(self, listing_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM listing_snapshots
                WHERE listing_id = ?
                ORDER BY observed_at ASC
                """,
                (listing_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_listings(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM listings"
            ).fetchone()
        return int(row["count"])

    def count_snapshots(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM listing_snapshots"
            ).fetchone()
        return int(row["count"])
