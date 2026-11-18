# Wlan

## Amazfit GTR 3 / GTS 3 über Bluetooth LE

Python-Skript (`amazfit_ble.py`), das sich per Bluetooth LE mit einer Amazfit-Uhr verbindet.
Läuft unter Windows, macOS und Linux.

### Installation

```bash
pip install -r requirements.txt
```

### Benutzung

```bash
python amazfit_ble.py scan                 # Uhr in der Nähe finden
python amazfit_ble.py info                 # Hersteller, Modell, Firmware, Akku
python amazfit_ble.py services             # alle GATT-Dienste auflisten
python amazfit_ble.py hr --dauer 60        # Herzfrequenz live mitlesen
```

Ohne `--address` sucht das Skript automatisch nach der Uhr. Mit
`--address AA:BB:CC:DD:EE:FF` verbindet es sich direkt (unter macOS ist die
Adresse eine UUID, die `scan` anzeigt).

### Hinweise

- Die Uhr sollte entsperrt und in der Nähe sein. Ist sie gerade mit dem Handy
  (Zepp-App) verbunden, kann eine zweite Verbindung fehlschlagen – dann am Handy
  kurz Bluetooth ausschalten.
- Für Herzfrequenz-Daten muss auf der Uhr ggf. die Herzfrequenz-Freigabe für
  andere Geräte aktiviert sein.
- Benachrichtigungen, Schritte, Schlaf usw. laufen über das verschlüsselte
  Zepp-OS-Protokoll und brauchen den Auth-Key aus der Zepp-App (noch nicht
  umgesetzt).
