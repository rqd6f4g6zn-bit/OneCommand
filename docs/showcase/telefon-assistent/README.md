# Showcase: Telefon-KI-Assistent für „Nordlicht Tee“

Gebaut aus einem einzigen Prompt:

```
/onecommand:onecommand "Telefon-KI-Assistent für den Kundensupport unseres Onlineshops Nordlicht Tee, Profi-Niveau:
beantwortet Fragen zu Öffnungszeiten, Versand und Rückgabe aus unserer Wissensbasis, gibt den Bestellstatus durch,
legt Tickets an, vereinbart Rückrufe und verbindet bei Bedarf mit einem Mitarbeiter"
```

OneCommand erkannte den Blueprint `phone-assistant` (Stufe `pro`) und baute daraus die Telefonanlage: Twilio-Webhooks
mit Signaturprüfung, eine Dialog-Engine, eine Wissensbasis, Aktionen (Bestellstatus, Ticket, Rückruf), die Übergabe
an Mitarbeiter, ein Gesprächsprotokoll mit maskierten Daten, Auswertungen und eine Verwaltungsoberfläche für drei
Rollen.

| | |
|---|---|
| Stack | Next.js 16, React 19, Prisma, SQLite, Tailwind; Twilio, Deepgram, Azure Neural TTS (im Test durch Fakes ersetzt) |
| Abnahme | 61 Kriterien, 60/60 automatische Abnahmetests grün, 11/11 Testanrufe grün, 54 Screenshots im Rundgang |
| Antwortzeit | unter 50 ms pro Gesprächszug in der Dialog-Engine |

Die Bilder zeigen die Produktionsversion mit Demo-Daten, angemeldet als `admin@nordlicht-tee.demo`. Sie wurden
nicht nachbearbeitet. Gebaut wurde mit v1.10.0.

## Testanruf-Simulator: dieselbe Dialog-Engine wie bei echten Anrufen
![Testanruf mit Bestellstatus, Öffnungszeiten und Rückgabe](02-testanruf-simulator.png)

## Dashboard
![Dashboard mit Automatisierungsquote, Übergaben, Gesprächsdauer und häufigsten Anliegen](01-dashboard.png)

## Gespräch mit Übergabe an eine Mitarbeiterin
![Transkript mit Übergabe-Zusammenfassung](03-transkript.png)

## Wissensbasis: aus diesen Artikeln antwortet der Assistent
![Wissensbasis](04-wissensbasis.png)

## Stimme und Datenschutz: Aufzeichnung nur mit Hinweis, Löschfristen, Löschung pro Rufnummer
![Einstellungen Stimme und Datenschutz](05-einstellungen.png)

## Mobil
<img src="06-mobil-dashboard.png" width="320" alt="Dashboard auf dem Handy">

## Was die Prüfungen von v1.11.0 an diesem Build finden

Der Build bestand alle Prüfungen von v1.10.0. Die neuen Prüfungen von v1.11.0 finden daran trotzdem Fehler. Für die
Testanrufe sind das genau die Fälle, die ein echter Test mit Anrufersätzen gezeigt hat:

| Pflicht-Testanruf / Prüfung | Antwort dieses Builds | Ergebnis |
|---|---|---|
| Small Talk: „Ja, hallo“ | „Das habe ich leider nicht verstanden. Ich verbinde Sie mit einem Mitarbeiter …“ | ✗ |
| Beschwerde: „Schon wieder falsch geliefert!“ | „Wie bitte? Das habe ich leider nicht verstanden.“ | ✗ |
| Folgefrage nach Bestellung 4711: „Wann kommt es denn genau?“ | „Wie lautet Ihre Bestellnummer?“ | ✗ |
| Bekannte Nummer: „Ändern Sie bitte die Lieferadresse“ | gibt den Bestellstatus durch, keine Prüfung | ✗ |
| Taste 0 (Übergabe) | spricht über TwiML `<Say>`, also mit Twilios Roboterstimme | ✗ |
| Rundgang: Dashboard und Gesprächsprotokoll | zeigen `order_status` und `knowledge_question` statt deutscher Namen | ⚠ |

Ab v1.11.0 lässt jeder dieser Fehler den Build durchfallen oder wird beim Durchsehen der Screenshots gemeldet. Die
Regeln dafür stehen im Skill `voice-agent`.

## Design-Prüfung: vorher und nachher

Die Oberfläche funktionierte, sah aber nach Vorlage aus. Die Design-Prüfung der UI-Tour (ab v1.11.0) misst jede Seite
und meldet an diesem Build 22 Befunde:

| Befund | Ursache im Code |
|---|---|
| Schrift ist die Systemschrift (DejaVu unter Linux, Segoe unter Windows) | CSS nennt nur `ui-sans-serif` / `ui-serif` |
| `callback`, `order_status` in Monospace als Beschriftung | Labels vorhanden (`INTENT_LABELS`), aber nicht benutzt |
| Zeilenlinien fehlen in der letzten Spalte jeder Tabelle | `last:border-b-0` an der Zelle statt an der letzten Zeile |
| Sidebar-Hintergrund endet nach 900 px | Hintergrund am `sticky h-screen`-Element statt an der Spalte |

Mit den Regeln aus `oc-frontend-design` → „Visual quality bar“ angewendet (selbst gehostete Schriften Fraunces und
Manrope, Labels, Linien an der Zeile, Hintergrund an der Spalte) meldet derselbe Rundgang **0 Befunde**:

![Dashboard nach den Design-Regeln](07-dashboard-neu.png)

![Wissensbasis nach den Design-Regeln](08-wissensbasis-neu.png)

Neue Builds schreiben vor der ersten Komponente einen Design-Brief (`.onecommand/design.md`: Charakter, Schriften,
Markenpalette, Wiedererkennungsmerkmal). Die Tour hält den Build daran fest.

---
Gebaut mit OneCommand · USC Software UG
