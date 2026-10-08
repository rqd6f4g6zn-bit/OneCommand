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

## Was die Design-Prüfung von v1.12.0 an diesem Build findet

Die Oberfläche funktioniert, sieht aber nach Vorlage aus. Die Design-Prüfung der UI-Tour misst jede Seite und meldet
an diesem Build 22 Befunde. Jede Ursache ist jetzt eine Regel im Skill `oc-frontend-design`, nicht eine Korrektur
an dieser App:

| Befund | Ursache im gebauten Code | Regel im Skill |
|---|---|---|
| Schrift ist die Systemschrift (DejaVu unter Linux, Segoe unter Windows) | CSS nennt nur `ui-sans-serif` und `ui-serif` | Schriften selbst ausliefern |
| `callback` und `order_status` als Beschriftung | `INTENT_LABELS` existiert, wird aber nicht benutzt | jeder Code-Wert läuft über eine Label-Map |
| Zeilenlinien fehlen in der letzten Spalte jeder Tabelle | `last:border-b-0` an der Zelle | Linie an der Zeile ziehen |
| Sidebar-Hintergrund endet nach 900 px | Hintergrund am `sticky h-screen`-Element | Hintergrund an die Spalte |

Der eigentliche Grund für das Vorlagen-Aussehen: Die Agenten haben den Design-Skill nie geladen. Ab v1.12.0 wird
das Laden geprüft, und der Build hält an, wenn ein Skill fehlt.

Die Bilder in diesem Ordner stammen unverändert aus dem Build. Bilder eines Builds mit v1.12.0 kommen hinzu, sobald
ein kompletter Build damit gelaufen ist.

---
Gebaut mit OneCommand · USC Software UG
