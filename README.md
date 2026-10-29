# 📚 Boketikett-generator for Dymo LabelWriter 450 (TwinTurbo)

Genererer boketiketter for Tysnes folkebibliotek basert på ISBN-oppslag mot Ája (Biblioteksentralen), med Open Library som fallback.

---

## Krav

- **Python 3.10 eller nyare** – https://www.python.org/downloads/
  - ⚠️ Hugs å hake av **"Add Python to PATH"** under installasjonen
- **Dymo Connect** installert på PC-en (følgjer med skrivaren)

---

## Installasjon

1. Dobbeltklikk på **`installer.bat`** – dette installerer nødvendige Python-pakkar (sjå `requirements.txt`)
2. Ferdig!

---

## Nettlesarversjonen (ny)

Programmet kan òg brukast i nettlesaren, i ei fane ved sida av dei andre.

1. Dobbeltklikk **`start-web.bat`**. Eit svart vindauge opnar seg, og nettlesaren opnar **http://localhost:8765**.
2. La det svarte vindauget stå ope (det kan minimerast). Lukkar du det, stoppar programmet.
3. Lag gjerne eit bokmerke til http://localhost:8765, eller fest fana.

Slik fungerer det: `server.py` køyrer på PC-en og gjer Ája-oppslaga og utskrifta (via `dymo-sdk`, som før). Nettsida i `web/` er berre skjermen. Programmet svarar berre på førespurnader frå denne PC-en.

Nytt i nettlesarversjonen:
- **Førehandsvising** av etiketten slik han blir skriven ut, oppdatert medan du skriv
- Endringar i felta blir lagra med ein gong – ingen «Lagre»-knapp
- Lista blir verande om du lastar sida på nytt, og utskrivne bøker blir merkte
- Etter utskrift går programmet vidare til neste bok i lista
- Snarvegar: **Ctrl+Enter** skriv ut, **Delete** fjernar, **pil opp/ned** blar i lista

**Start automatisk ved innlogging:** Trykk Windows+R, skriv `shell:startup` og trykk Enter. Lag ein snarveg til `start-web.bat` i mappa som opnar seg. Vil du ikkje at nettlesaren skal opne seg kvar gong, legg til ` --ikkje-opne` bak `start-web.bat` i målfeltet til snarvegen.

---

## Bruk (den gamle versjonen)

1. Dobbeltklikk **`start.bat`** for å opne programmet
2. **Scan eller skriv inn ISBN** i feltet øvst til venstre, trykk Enter (eller "Legg til")
   - Programmet slår automatisk opp boka i **Ája SRU** (tittel, forfattar, hyllekode, dewey, serie, målform, sjanger m.m.)
   - Finst boka ikkje i Ája, blir det automatisk prøvd mot **Open Library** i staden (merkt med "!" i lista)
   - Du kan òg skrive inn tittel direkte dersom du ikkje har ISBN for handa
3. Boka dukkar opp i **"Bøker i lista"** til venstre – legg til fleire bøker etter kvart
4. Klikk på ei bok i lista for å **kontrollere/redigere** felta til høgre:
   - Tittel, forfattar, hyllekode, dewey, kategori, emne (for sakprosa), serienavn, nummer i serie, målform
   - Kategori blir automatisk føreslått ut frå sjanger/alder/språk, men kan endrast manuelt
   - Malen (Standard / Biletbok) blir vist og oppdatert automatisk ut frå kategori
5. Klikk **"Lagre endringar"** for å lagre justeringar på boka
6. Skriv ut:
   - **"Skriv ut denne"** (eller Ctrl+Enter) – skriv ut etiketten for boka som er vald
   - **"Skriv ut ALLE etiketter"** – skriv ut heile lista
   - **"Serieliste"** – lag ein eigen etikett med opptil 5 bøker i same serie, med moglegheit til å redigere kvar linje og markere kva for ei bok som er den aktive før utskrift

Andre snarvegar: **Delete** fjernar vald bok frå lista.

---

## Etikettstørrelse og malar

Etikettane er **32 × 57 mm Dymo Durable-etikettar** (Dymo-delenummer S0722540, multipurpose), skrivne ut via `dymo-sdk`/Dymo Connect (`https://127.0.0.1:41951/DYMO/DLS/Printing/PrintLabel`).

Tre etikettmalar (`.dymo`-filer i same mappe som `app.py`):

| Fil | Bruk |
|---|---|
| `Standard.dymo` | Vanlege bøker – forfattarforkortelse/hyllekode |
| `Biletboker.dymo` | Biletbøker – tilpassa layout |
| `Serieliste.dymo` | Serieliste med fleire titlar/nummer på éin etikett |

Kategorisering (Standard vs. Biletbok-mal, samt merkelappar som Fantasy, Krim, Manga, Teikneserie, Engelsk, Lyrikk osv.) blir styrt automatisk av programmet ut frå sjanger, alder og språk henta frå Ája.

For sakprosa (Dewey utanfor 800–899) blir forkortinga på etiketten sett saman av **dewey + hyllekode** i staden for berre hyllekode. Emnet på sakprosa-etikettane er grovt inndelt frå Dewey, med nokre eigne emne (t.d. Fotball, Gaming, Film, Helse, Første/Andre verdskrig, Norge, Biografi). Historie frå andre land får verdsdelen.

---

## Filer i repoet

| Fil | Innhald |
|---|---|
| `app.py` | Den gamle versjonen (eige vindauge) |
| `server.py` | Nettlesarversjonen – startar den lokale nettstaden |
| `kjerne.py` | Oppslag, kategoriar, etikettgenerering og utskrift (brukt av `server.py`) |
| `web/index.html` | Nettsida |
| `start-web.bat` | Startar nettlesarversjonen |
| `installer.bat` | Installerer Python-pakkane |
| `start.bat` | Startar den gamle versjonen |
| `requirements.txt` | Liste over Python-pakkar |
| `*.dymo` | Etikettmalane |

---

## Skifte skrivarnamn

Skriv inn det eksakte skrivarnamnet slik det står i Windows under
**Innstillingar → Bluetooth og einingar → Skrivarar og skannarar**, og trykk **"Lagre"** ved skrivarfeltet nedst i vindauget. Innstillinga blir lagra i `.boketikett_settings.json` i heimemappa.

Standard namn: `DYMO LabelWriter 450 TwinTurbo`

---

## Feilsøking

| Problem | Løysing |
|---|---|
| "Python er ikkje installert" | Last ned frå python.org, hugs "Add to PATH" |
| Boka blir ikkje funnen | Sjekk ISBN-et; prøv å søkje på tittel i staden. Open Library blir automatisk brukt som fallback, men manglar ofte dewey/serie – fyll inn manuelt |
| Ingenting blir skrive ut | Sjekk at skrivarnamnet er korrekt og at Dymo Connect køyrer |
| Feil kategori/mal | Rediger "Kategori"-feltet manuelt – malen oppdaterer seg automatisk |

---

## Framtidige moglegheiter

Direkte integrasjon mot **Bibliofil WebAPI** er vurdert som eit mogleg framtidig alternativ/supplement til Ája-oppslaget. Ta kontakt med Bibliofil på **webapi@bibsyst.no** for å aktivere API-tilgang dersom dette blir aktuelt.
