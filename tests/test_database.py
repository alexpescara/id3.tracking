from src.database.repository import TrackingRepository


def make_listing(listing_id="test-123", price=26900):
    return {
        "listing_id": listing_id,
        "url": f"https://example.com/annunci/{listing_id}",
        "title": "Volkswagen ID.3 Pro Performance 58 kWh",
        "price_eur": price,
        "mileage_km": 15000,
        "registration_year": 2024,
        "battery_kwh": 58,
        "power_hp": 204,
        "seller": "Test Dealer",
        "description": "Test",
        "equipment": "",
        "restyling_candidate": True,
        "infotainment_129_candidate": None,
        "confidence_score": 0,
        "classification_evidence": "anno 2024; batteria 58 kWh",
    }


def test_save_new_listing(tmp_path):
    repository = TrackingRepository(
        tmp_path / "test.db",
        timezone="Europe/Rome",
    )

    repository.save_listing(
        make_listing(),
        observed_at="2026-09-18T10:00:00+02:00",
    )

    assert repository.count_listings() == 1
    assert repository.count_snapshots() == 1

    listing = repository.get_listing("test-123")
    assert listing is not None
    assert listing["price_eur"] == 26900
    assert listing["first_seen"] == "2026-09-18T10:00:00+02:00"


def test_second_observation_preserves_first_seen(tmp_path):
    repository = TrackingRepository(
        tmp_path / "test.db",
        timezone="Europe/Rome",
    )

    repository.save_listing(
        make_listing(price=26900),
        observed_at="2026-09-18T10:00:00+02:00",
    )
    repository.save_listing(
        make_listing(price=25900),
        observed_at="2026-09-19T10:00:00+02:00",
    )

    assert repository.count_listings() == 1
    assert repository.count_snapshots() == 2

    listing = repository.get_listing("test-123")
    assert listing["first_seen"] == "2026-09-18T10:00:00+02:00"
    assert listing["last_seen"] == "2026-09-19T10:00:00+02:00"
    assert listing["price_eur"] == 25900

    history = repository.get_history("test-123")
    assert [row["price_eur"] for row in history] == [26900, 25900]


def test_same_observation_is_not_duplicated(tmp_path):
    repository = TrackingRepository(
        tmp_path / "test.db",
        timezone="Europe/Rome",
    )

    timestamp = "2026-09-18T10:00:00+02:00"

    repository.save_listing(make_listing(), observed_at=timestamp)
    repository.save_listing(make_listing(), observed_at=timestamp)

    assert repository.count_listings() == 1
    assert repository.count_snapshots() == 1
