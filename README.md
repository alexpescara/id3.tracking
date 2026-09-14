# ID.3 Market Monitor

Open-source monitor per annunci usati di Volkswagen ID.3, con particolare attenzione alle versioni restyling dotate del display/infotainment centrale da 12,9".

> **Stato:** V0.1 — primo scraper + normalizzazione + esportazione CSV.

## Obiettivi

- raccogliere periodicamente annunci pubblici;
- normalizzare prezzo, chilometraggio, anno, batteria, potenza e descrizione;
- identificare candidati ID.3 restyling / 12,9";
- mantenere in futuro lo storico dei prezzi;
- produrre statistiche e alert;
- usare esclusivamente software gratuito/open source.

## Nota importante su scraping

Il progetto è predisposto con un'architettura a sorgenti (`source adapters`). Lo scraper incluso è volutamente conservativo: usa pagine pubbliche e non tenta di aggirare CAPTCHA, login, rate limit, sistemi anti-bot o altre misure di protezione.

Prima di usare lo scraper su un sito specifico, verifica sempre robots.txt e termini d'uso applicabili. Mantieni una frequenza di richiesta bassa e rispettosa.

## Requisiti

- Python 3.11+
- Git
- Chromium/Chrome installato oppure Playwright Chromium

## Installazione

```bash
git clone https://github.com/<TUO-USERNAME>/id3-market-monitor.git
cd id3-market-monitor

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium
```

## Configurazione

Copia:

```bash
copy config.example.yaml config.yaml
```

su Windows, oppure:

```bash
cp config.example.yaml config.yaml
```

Modifica `config.yaml`.

## Primo scraper

```bash
python -m src.main
```

I risultati vengono salvati in:

```text
data/raw/
data/processed/listings.csv
```

Per eseguire lo scraper in modalità visibile:

```bash
python -m src.main --headed
```

## Output

Il CSV contiene, tra gli altri:

- `listing_id`
- `source`
- `url`
- `title`
- `price_eur`
- `mileage_km`
- `registration_year`
- `battery_kwh`
- `power_hp`
- `description`
- `seller`
- `restyling_candidate`
- `infotainment_129_candidate`
- `confidence_score`

## Architettura

```text
id3-market-monitor/
├── .github/workflows/
├── config/
├── data/
│   ├── raw/
│   └── processed/
├── src/
│   ├── models/
│   ├── scrapers/
│   ├── parsers/
│   ├── classifiers/
│   └── main.py
├── tests/
├── .gitignore
├── config.example.yaml
├── requirements.txt
└── README.md
```

## Roadmap

- [x] V0.1 struttura progetto
- [x] primo adapter scraper
- [x] normalizzazione CSV
- [x] classificatore iniziale 12,9"
- [ ] storico giornaliero
- [ ] deduplicazione robusta
- [ ] dashboard
- [ ] GitHub Actions
- [ ] alert Telegram
- [ ] analisi ribassi
- [ ] stima prezzo futura
- [ ] supporto a ulteriori fonti

## Licenza

MIT. Verifica comunque i termini dei singoli siti prima di raccogliere o redistribuire dati.
