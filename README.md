# Autoposter für @shortheaven3

Veröffentlicht täglich genau einen geplanten Instagram-Beitrag über die Instagram Graph API.

## Warum es so gebaut ist

Instagram bietet **keine** Terminierung über die API — es gibt keinen Parameter für einen
zukünftigen Zeitpunkt. Ein externer Zeitgeber ist deshalb zwingend; GitHub Actions liefert
ihn kostenlos.

Die Bilder liegen im Repository, weil `raw.githubusercontent.com` permanente URLs ausgibt.
Canva-Exportlinks verfallen nach 12–24 Stunden und sind für geplante Beiträge wertlos.
Deshalb muss dieses Repository **öffentlich** bleiben — Instagram muss die Bilder abrufen können.

## Aufbau

```
publish.py                      Skript: liest Plan, erzeugt Container, veröffentlicht
schedule.json                   Redaktionsplan mit Datum, Bild, Caption
images/                         die Beitragsbilder (JPG, 1080 × 1350)
.github/workflows/publish.yml   Zeitgeber, täglich 05:00 UTC
```

## Einrichtung

1. **Secrets setzen** unter *Settings → Secrets and variables → Actions → New repository secret*:

   | Name | Wert |
   |---|---|
   | `IG_USER_ID` | `26893495943657550` |
   | `IG_ACCESS_TOKEN` | Long-Lived Token aus dem Meta-Entwicklerportal |

2. **Schreibrechte prüfen** unter *Settings → Actions → General → Workflow permissions*:
   "Read and write permissions" muss aktiv sein, damit der Workflow `schedule.json`
   zurückschreiben kann.

3. **Bilder ablegen** in `images/`, benannt exakt wie in `schedule.json`.

4. **Trockenlauf starten**: Reiter *Actions* → *Instagram Autoposter* → *Run workflow* →
   `dry_run` auf `true` lassen. Das Log zeigt, was veröffentlicht würde, ohne etwas zu
   veröffentlichen.

5. **Scharf schalten**: Sobald der Trockenlauf sauber durchläuft, übernimmt der tägliche
   Cron ab dem nächsten Morgen.

## Schutzmechanismen

* **Ein Beitrag pro Lauf** — auch wenn mehrere Einträge überfällig sind. Verhindert, dass
  mehrere Beiträge mit identischem Zeitstempel im Feed landen.
* **Idempotenz** — Einträge mit gesetzter `published_id` werden übersprungen. Der Workflow
  schreibt die ID nach erfolgreicher Veröffentlichung automatisch zurück ins Repository.
* **Kontingentprüfung** — vor jeder Veröffentlichung wird das 24-Stunden-Limit abgefragt
  (rund 100 Beiträge) und bei Erschöpfung abgebrochen.
* **Trockenlauf** — `python publish.py --dry-run` oder `DRY_RUN=1`.
* **Bildprüfung** — fehlt eine in `schedule.json` genannte Datei in `images/`, bricht der
  Lauf ab, bevor irgendetwas an Instagram geht.

## Format von `schedule.json`

Ein Eintrag ist ein Karussell, sobald `images` (Mehrzahl) gesetzt ist; sonst zählt `image`.
`published_id` bleibt `null`, bis das Skript den Beitrag veröffentlicht hat.

## Wartung

* **Der Access Token läuft nach 60 Tagen ab.** Das ist die häufigste Ursache dafür, dass
  solche Setups stillschweigend aufhören zu funktionieren. Erneuern im Meta-Entwicklerportal
  und das Secret `IG_ACCESS_TOKEN` aktualisieren.
* **Das Konto muss öffentlich sein.** Ein privates Konto kann über die API nicht
  veröffentlichen.
