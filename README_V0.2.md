# ID.3 Market Monitor — V0.2

La V0.2 introduce un archivio SQLite per conservare lo storico delle rilevazioni.

## Flusso

AutoScout24 → scraper → classifier → filtri → CSV + SQLite

Il database viene creato automaticamente in:

```text
data/id3_tracking.db
```

### Tabelle

`listings` contiene lo stato più recente di ogni annuncio.

`listing_snapshots` contiene una rilevazione storica per ogni esecuzione e permette di ricostruire l'andamento di prezzo e chilometraggio.

## Esecuzione

Il comando dello scraper non cambia:

```bash
python -m src.main
```

Dopo l'esecuzione saranno aggiornati:

```text
data/processed/listings.csv
data/id3_tracking.db
```

## Test

```bash
pytest
```

## Nota

La V0.2 non determina ancora quando un annuncio è realmente scomparso dal mercato. Gli annunci rilevati vengono aggiornati come `active`; la gestione affidabile degli annunci non più presenti verrà affrontata in uno step successivo, evitando falsi "rimossi" causati da scraping incompleti.
