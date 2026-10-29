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

## Bruk

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
| `app.py` | Sjølve programmet |
| `installer.bat` | Installerer Python-pakkane |
| `start.bat` | Startar programmet |
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
