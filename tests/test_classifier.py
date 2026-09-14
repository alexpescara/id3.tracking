from src.classifiers.id3 import classify_listing


def test_129_positive():
    item = {
        "title": "Volkswagen ID.3 Pro 58 kWh",
        "description": "Nuovo infotainment con display 12,9 pollici",
        "registration_year": 2024,
        "battery_kwh": 58,
    }
    result = classify_listing(item)
    assert result["infotainment_129_candidate"] is True
    assert result["confidence_score"] >= 50


def test_old_display_not_positive():
    item = {
        "title": "Volkswagen ID.3",
        "description": "Display centrale da 12 pollici",
        "registration_year": 2023,
        "battery_kwh": 58,
    }
    result = classify_listing(item)
    assert result["infotainment_129_candidate"] is False
