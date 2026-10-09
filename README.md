# Hikvision User & PIN Control

Home Assistant Custom Integration zur Verwaltung von Benutzern und Zugangskarten an Hikvision Zutrittskontrollgeräten (z.B. DS-K1T342 Serie).

## Features

- Benutzer anlegen, löschen und Gültigkeit verlängern
- QR-Code Generierung für Zugangskarten
- Zwei native Lovelace Dashboard Cards (Benutzer + Ereignisse)
- Natives Sidebar-Panel (nutzt die HA-Anmeldung)
- PIN-Schutz für sensible Aktionen (Löschen, QR, Verlängern)
- Geschützte Benutzer (nicht löschbar)
- HA Services für Automationen
- Sensoren: Benutzeranzahl & letztes Ereignis

## Installation

### HACS (empfohlen)

1. HACS öffnen → **Integrationen** → **Drei Punkte** → **Benutzerdefinierte Repositories**
2. Repository-URL eintragen und als Kategorie **Integration** auswählen
3. "Hikvision User & PIN Control" installieren
4. Home Assistant neu starten

### Manuell

1. Den Ordner `custom_components/hikvision_userpin/` in das `custom_components/` Verzeichnis der HA-Installation kopieren
2. Home Assistant neu starten

### Voraussetzungen

Die folgenden Python-Pakete werden automatisch installiert:

- `requests`
- `qrcode`
- `Pillow`

## Konfiguration

### Integration einrichten

1. **Einstellungen** → **Geräte & Dienste** → **Integration hinzufügen**
2. Nach "Hikvision User & PIN Control" suchen
3. Verbindungsdaten eingeben:

| Feld | Beschreibung | Beispiel |
|------|-------------|---------|
| Geräte-URL | HTTP(S)-Adresse des Geräts | `http://192.168.1.100` |
| Benutzername | Admin-Benutzer des Geräts | `admin` |
| Passwort | Passwort des Geräts | |
| SSL-Zertifikat prüfen | SSL-Verifizierung aktivieren | `false` |

### Optionen

Nach der Einrichtung über **Konfigurieren** (oder Drei-Punkte-Menü → Optionen) erreichbar:

| Option | Beschreibung | Standard |
|--------|-------------|----------|
| `timeout` | HTTP-Timeout in Sekunden | `8.0` |
| `protected_employee_nos` | Geschützte Mitarbeiter-IDs, kommagetrennt (werden nicht gelöscht) | leer |
| `allowed_events` | Erlaubte Ereigniscodes, z.B. `5/75,5/38` | `5/75,5/38,5/39,5/8` |
| `scan_interval` | Abfrageintervall in Sekunden | `300` |

## Lovelace Cards

Die Integration stellt zwei Custom Lovelace Cards bereit:

### Benutzer-Card

Zeigt die Benutzertabelle mit QR-Code, Verlängern und Löschen sowie ein einklappbares Formular zum Anlegen neuer Benutzer.

```yaml
type: custom:hikvision-userpin-users
title: Zutrittskontrolle        # optional, Standard: "Hikvision Benutzer"
pin: "1234"                     # optional, PIN für QR/Verlängern/Löschen
entry_id: abc123                # optional, bei mehreren Geräten
```

| Option | Beschreibung | Pflicht |
|--------|-------------|---------|
| `title` | Überschrift der Card | Nein |
| `pin` | PIN-Code zum Schutz sensibler Aktionen | Nein |
| `entry_id` | Config-Entry-ID bei Multi-Device-Setup | Nein |

### Ereignisse-Card

Zeigt Zutrittsereignisse mit Seitennavigation (Paging).

```yaml
type: custom:hikvision-userpin-events
title: Letzte Ereignisse        # optional, Standard: "Hikvision Ereignisse"
page_size: 10                   # optional, Einträge pro Seite (Standard: 10)
entry_id: abc123                # optional, bei mehreren Geräten
```

| Option | Beschreibung | Pflicht |
|--------|-------------|---------|
| `title` | Überschrift der Card | Nein |
| `page_size` | Anzahl Ereignisse pro Seite | Nein |
| `entry_id` | Config-Entry-ID bei Multi-Device-Setup | Nein |

### Card hinzufügen

1. Dashboard öffnen → **Bearbeiten** → **Card hinzufügen**
2. Nach "Hikvision" suchen oder manuell YAML eingeben
3. Die Cards sind iPhone/Mobil-optimiert (Touch-Targets, kein Auto-Zoom)

## Sensoren

Die Integration erstellt zwei Sensoren pro Gerät:

| Sensor | Beschreibung | Attribute |
|--------|-------------|-----------|
| `sensor.*_user_count` | Anzahl der Benutzer auf dem Gerät | `usernames`, `employee_numbers` |
| `sensor.*_last_event` | Letztes Zutrittsereignis | `time`, `employee`, `code` |

## Services

Alle Services können in Automationen und Skripten verwendet werden.

### `hikvision_userpin.create_user`

Neuen Benutzer mit Zugangskarte anlegen.

```yaml
service: hikvision_userpin.create_user
data:
  config_entry_id: "abc123"
  name: "Max Mustermann"
  start_date: "2025-01-01"
  duration: "7d"            # 1d, 7d, 14d, 4w, 3m, 12m, forever, custom
  end_date: "2025-03-01"   # nur bei duration: custom
```

### `hikvision_userpin.delete_user`

Benutzer vom Gerät löschen.

```yaml
service: hikvision_userpin.delete_user
data:
  config_entry_id: "abc123"
  employee_no: "ABC123DEF456"
```

### `hikvision_userpin.extend_user`

Gültigkeit eines bestehenden Benutzers verlängern.

```yaml
service: hikvision_userpin.extend_user
data:
  config_entry_id: "abc123"
  employee_no: "ABC123DEF456"
  duration: "7d"
  begin_date: "2025-01-01"
  current_end: "2025-01-08"
```

## Sidebar-Panel

Neben den Lovelace Cards wird automatisch ein natives Sidebar-Panel unter **Hikvision UserPin** registriert. Es bettet dieselben beiden Lovelace Cards (Benutzer + Ereignisse) ein – es gibt also keine zweite Oberfläche und keinen iframe mehr.

Alle Aufrufe des Panels laufen über die normale Home-Assistant-Anmeldung: Daten werden per `hass.callApi` (mit Bearer-Token) geholt, Aktionen per `hass.callService` ausgeführt. Ohne gültige HA-Session ist kein Endpunkt der Integration erreichbar.

## Fehlerbehebung

### Benutzer werden nicht angelegt oder gelöscht

Hikvision-Geräte antworten auf Zutrittskontroll-Befehle **auch bei Fehlern mit
HTTP 200** – das eigentliche Ergebnis steht im JSON-Body (`statusCode`). Die
Integration wertet diesen Status seit v1.1.0 aus und meldet Fehler nun aktiv:

- **Services** (`create_user`, `delete_user`, `extend_user`, `deactivate_user`)
  lösen bei einer Geräte-Ablehnung einen Fehler mit der Geräte-Meldung aus
  (sichtbar in der Aktion/Automation).
- **Panel & Cards** protokollieren die Geräte-Meldung im Home-Assistant-Log
  (`Einstellungen → System → Protokolle`, Filter `hikvision_userpin`).

Typische Geräte-Meldungen und Ursachen:

| `subStatusCode` | Bedeutung |
|-----------------|-----------|
| `deviceUserAlreadyExist` | Benutzer/Karte existiert bereits (wird als Erfolg gewertet) |
| `employeeNoNotExist` | Zu löschender Benutzer existiert nicht (wird als Erfolg gewertet) |
| `notSupport` / `invalidContent` | Firmware akzeptiert das Payload-Feld nicht |
| `deviceIsBusy` / `capacity...` | Gerät ausgelastet bzw. Speicher voll |

Wenn ein Benutzer zwar angelegt wird, aber keinen Zutritt erhält, liegt es oft
an der Zeitzone der Gültigkeit. Die Integration sendet die Gültigkeit daher mit
`timeType: local`, damit das Gerät sie nicht als UTC interpretiert.

## Unterstützte Geräte

Getestet mit Hikvision Zutrittskontrollgeräten, die die ISAPI-Schnittstelle unterstützen:

- `ISAPI/AccessControl/UserInfo/` (Benutzerverwaltung)
- `ISAPI/AccessControl/CardInfo/` (Kartenverwaltung)
- `ISAPI/AccessControl/AcsEvent` (Ereignisse)

## Dateistruktur

```
custom_components/hikvision_userpin/
├── __init__.py          # Integration Setup
├── client.py            # Hikvision ISAPI Client
├── config_flow.py       # Config & Options Flow
├── const.py             # Konstanten
├── coordinator.py       # DataUpdateCoordinator
├── manifest.json        # Integration Manifest
├── panel.py             # Auth-geschützte API-Views & Sidebar-Panel
├── sensor.py            # Sensor-Entitäten
├── services.py          # Service-Handler
├── services.yaml        # Service-Definitionen
├── strings.json         # Englische Strings
├── translations/
│   └── de.json          # Deutsche Übersetzung
└── www/
    ├── hikvision-userpin-card.js   # Lovelace Cards
    └── hikvision-userpin-panel.js  # Sidebar-Panel (bettet die Cards ein)
```

## Sicherheit

> **Wichtig für Nutzer von Version 1.1.0 und älter**
>
> Bis einschließlich 1.1.0 waren die Panel-Endpunkte (`/api/hikvision_userpin/...`) ohne Login erreichbar (`requires_auth = False`). Bei einer öffentlich erreichbaren Home-Assistant-Instanz konnten dadurch Unbefugte Benutzer samt Karten-IDs auslesen sowie Zugänge anlegen, löschen oder verlängern.
>
> Ab Version 1.2.0 erfordern alle Endpunkte eine gültige HA-Authentifizierung. **Nach dem Update sollten alle Karten-IDs/PINs geprüft werden, die über eine betroffene Version vergeben wurden – im Zweifel löschen und neu vergeben.**
