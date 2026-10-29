"""
Kjernelogikk for boketikett-generatoren
=======================================
Oppslag i Ája/Open Library, kategorisering, generering av .dymo-filer
og utskrift. Blir brukt av server.py (nettlesarversjonen). Har ingen
GUI-avhengigheiter.
"""

import os, re, json, tempfile, threading, queue, requests, subprocess, time
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from pathlib import Path
import xml.etree.ElementTree as ET

# ── Stiar ───────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
STANDARD_TMPL   = BASE_DIR / "Standard.dymo"
BILETBOK_TMPL   = BASE_DIR / "Biletboker.dymo"
SERIELISTE_TMPL = BASE_DIR / "Serieliste.dymo"
SETTINGS_FILE   = Path.home() / ".boketikett_settings.json"
# ── Innstillingar ────────────────────────────────────────────────────────────
def load_settings():
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    return {"printer": "DYMO LabelWriter 450 TwinTurbo"}

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f)

# ── Emne for sakprosa (grove kategoriar frå Dewey) ───────────────────────────
VERDSDELAR_HISTORIE = {"94": "Europa", "95": "Asia", "96": "Afrika",
                       "97": "Nord-Amerika", "98": "Sør-Amerika", "99": "Oseania"}

def _dewey_delar(dewey: str):
    """Returner (grunn, desimal) frå t.d. 'q 641.82' -> ('641', '82'). Tre siffer i grunn."""
    m = re.search(r"(\d+)(?:[.,](\d+))?", dewey or "")
    if not m:
        return "", ""
    return (m.group(1) + "00")[:3], m.group(2) or ""

def er_litteraturhistorie(dewey: str) -> bool:
    """Bøker OM litteratur (historie/kritikk): 801, 809, x20.9 eller -09 i nummeret."""
    g, des = _dewey_delar(dewey)
    if not g or g[0] != "8":
        return False
    return g in ("801", "809") or "09" in des or (g[2] == "0" and des.startswith("9"))

def dewey_til_emneord(dewey: str) -> str:
    """Grovt emneord frå Dewey, med eigne emne for utvalde område."""
    d = (dewey or "").strip().upper()
    if not d:
        return ""
    g, des = _dewey_delar(d)
    if not g:
        return "Biografi" if d.startswith("B") else ""
    full = g + ("." + des if des else "")
    if g.startswith("92"):
        return "Biografi"
    if er_litteraturhistorie(d):
        return "Litteraturhistorie"
    # Spesifikke område (sjekkast først)
    if full.startswith(("940.53", "940.54")):
        return "Andre verdskrig"
    if full.startswith("940.3"):
        return "Første verdskrig"
    if full.startswith("948.1"):
        return "Norge"
    if full.startswith("796.334"):
        return "Fotball"
    if full.startswith(("796.5", "799")):   # tur, camping, klatring, jakt og fiske
        return "Friluftsliv"
    if full.startswith("794.8"):
        return "Gaming"
    if full.startswith("791.4"):
        return "Film"
    if g == "792":
        return "Teater"
    if g in ("745", "746") or full.startswith(("646.2", "646.3", "646.4")):
        return "Handarbeid"
    if g in ("004", "005", "006"):   # datamaskinar, programmering, internett
        return "Informasjonsteknologi"
    h = g[0]
    if h == "1":
        return "Psykologi" if g.startswith("15") else "Filosofi"
    if h == "2":
        return "Religion"
    if h == "3":
        return "Økonomi" if g.startswith("33") else "Samfunn"
    if h == "4":
        return "Språk"
    if h == "5":
        return "Naturvitskap"
    if h == "6":
        if g.startswith("61"):
            return "Helse"
        if g.startswith("63"):
            return "Landbruk/husdyr"
        if g.startswith("65"):
            return "Økonomi"
        if g.startswith("64"):
            return "Heim og familie"
        return "Teknikk"
    if h == "7":
        if g.startswith("78"):
            return "Musikk"
        if g.startswith("79"):
            return "Sport" if g[:2] == "79" and g in ("796", "797", "798", "799") else "Fritid"
        return "Kunst"
    if h == "8":
        return "Litteratur"
    if h == "9":
        if g.startswith("91"):
            return "Geografi og reise"
        if g.startswith("93"):
            return "Oldtida"
        if g == "998":
            return "Polarområda"
        if g[:2] in VERDSDELAR_HISTORIE and g not in ("997", "999"):
            return VERDSDELAR_HISTORIE[g[:2]]
        return "Historie"
    return "Generelt"

# Alle emna dewey_til_emneord kan gi, til forslagslista i nettsida
EMNE = sorted({
    "Andre verdskrig", "Biografi", "Film", "Filosofi", "Fotball", "Friluftsliv", "Fritid",
    "Første verdskrig", "Gaming", "Generelt", "Geografi og reise", "Handarbeid",
    "Heim og familie", "Helse", "Historie", "Informasjonsteknologi", "Kunst",
    "Landbruk/husdyr", "Litteratur", "Litteraturhistorie", "Musikk", "Naturvitskap",
    "Norge", "Oldtida", "Polarområda", "Psykologi", "Religion", "Samfunn", "Sport",
    "Språk", "Teater", "Teknikk", "Økonomi", *VERDSDELAR_HISTORIE.values(),
})

def aldersgruppe(kode: str) -> str:
    """Returner 'barn', 'ungdom' eller 'vaksen' basert på MARC-alderskode."""
    kode = (kode or "").lower().strip()
    if kode in ("b", "bu"):
        return "barn"
    if kode in ("u", "mu", "vu"):
        return "ungdom"
    return "vaksen"

# ── Kategoriegikk ────────────────────────────────────────────────────────────
def bestem_kategori(sjangrar: list, alder: str, språk: str, er_sakprosa: bool) -> str:
    """Bestem etikettkategori basert på sjanger, alder og språk."""
    if er_sakprosa:
        return ""  # Sakprosa brukar tema + dewey

    # Engelsk overstyrer sjanger
    if språk == "eng":
        return {"barn": "Engelsk Barn", "ungdom": "Engelsk Ungdom"}.get(alder, "Engelsk Vaksen")

    # Manga og teikneserie overstyrer alt – sjekk FØRST (også før sakprosa-logikk)
    for s in sjangrar:
        sl = s.lower()
        if "manga" in sl:
            return {"barn": "Manga Barn", "ungdom": "Manga Ungdom"}.get(alder, "Manga Vaksen")
        if "teikneserie" in sl or "tegneserie" in sl or "teikneseriar" in sl or "comic" in sl:
            return {"barn": "Teikneserie Barn"}.get(alder, "Teikneserie Vaksen")

    # Biletbøker, humor, lyrikk, skodespel
    for s in sjangrar:
        sl = s.lower()
        if "lettlest" in sl or "lettlesen" in sl or "lesebøker" in sl or "lesebok" in sl:
            if alder == "barn":
                return "Lettlest Barn"
        if "humor" in sl:
            return "Humor Barn"
        if ("biletbok" in sl or "bildebok" in sl or "bildbok" in sl
                or "pekebok" in sl or "bilderoman" in sl or "biletroman" in sl
                or "bildebøker" in sl or "biletbøker" in sl):
            return "biletbøker"
        if "novelle" in sl and alder not in ("barn", "ungdom"):
            return "Noveller Vaksen"
        if "lyrikk" in sl or "dikt" in sl:
            return {"barn": "Lyrikk Barn", "ungdom": "Lyrikk Ungdom"}.get(alder, "Lyrikk Vaksen")
        if "skodespel" in sl or "dramatikk" in sl:
            return {"barn": "Skodespel Barn", "ungdom": "Skodespel Ungdom"}.get(alder, "Skodespel Vaksen")

    # Fantasy, Kriminal (inkl. thriller/spenning), Grøssar
    for s in sjangrar:
        sl = s.lower()
        if "fantasy" in sl:
            return {"barn": "Fantasy Barn", "ungdom": "Fantasy Ungdom"}.get(alder, "Fantasy Vaksen")
        if "krim" in sl or "thriller" in sl or "spenning" in sl:
            return {"barn": "Kriminal Barn", "ungdom": "Kriminal Ungdom"}.get(alder, "Kriminal Vaksen")
        if "grøss" in sl or "horror" in sl or "skrekk" in sl:
            return {"barn": "Grøssar Barn", "ungdom": "Grøssar Ungdom"}.get(alder, "Grøssar Vaksen")

    # Ingen kjend sjanger
    if alder == "ungdom":
        return "Roman Ungdom"
    if alder == "barn":
        return "Barnebøker"
    return "Roman Vaksen"

# ── Målform ──────────────────────────────────────────────────────────────────
def malfom_tekst(kode: str) -> str:
    return {"nob": "Bokmål", "nno": "Nynorsk", "eng": "Engelsk"}.get((kode or "").lower(), "Bokmål")

# ── Ája SRU-oppslag ──────────────────────────────────────────────────────────
NS = {
    "srw":  "http://www.loc.gov/zing/srw/",
    "mods": "http://www.loc.gov/mods/v3",
}
MNS = "info:lc/xmlns/marcxchange-v1"

def aja_oppslag(isbn: str) -> dict | None:
    """Slå opp ISBN i Ája, fell tilbake til Open Library viss ikkje funne."""
    isbn = re.sub(r"[\s-]", "", isbn)
    url = (f"https://sru.aja.bs.no/mlnb"
           f"?operation=searchRetrieve"
           f"&query=dc.identifier={isbn}"
           f"&recordSchema=marc21nor&maximumRecords=1")
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        bok = parse_mods(r.text)
        if bok:
            bok["kjelde"] = "aja"
            return bok
    except Exception:
        pass
    # Fallback: prøv Open Library
    return open_library_oppslag(isbn)


def open_library_oppslag(isbn: str) -> dict | None:
    """Fallback: slå opp ISBN i Open Library."""
    isbn = re.sub(r"[\s-]", "", isbn)
    url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        key = f"ISBN:{isbn}"
        if key not in data:
            return None
        b = data[key]

        # Forfattar
        forfattar = ""
        if b.get("authors"):
            forfattar = b["authors"][0].get("name", "")

        # Filtrer bort ikkje-latinske forfattarnamn (t.d. japanske teikn)
        if forfattar and not all(ord(c) < 0x0370 or c in ' ,.-\'' for c in forfattar):
            forfattar = ""

        # Forkortelse: 3 første bokstavar i etternamn
        forkortelse = ""
        if forfattar:
            etternamn = forfattar.split()[-1] if " " in forfattar else forfattar
            forkortelse = etternamn[:3].upper()

        # Trekk ut serie og serienummer frå tittelen (t.d. "Sakamoto Days, Vol. 4")
        tittel_full = b.get("title", "").strip()
        serie_tittel = ""
        serie_nummer = ""
        m = re.match(r'^(.+?),\s+[Vv]ol\.?\s*(\d+)', tittel_full)
        if not m:
            m = re.match(r'^(.+?)\s+[Vv]ol\.?\s*(\d+)', tittel_full)
        if not m:
            m = re.match(r'^(.+?),?\s+#(\d+)', tittel_full)
        if m:
            serie_tittel = m.group(1).strip()
            serie_nummer = m.group(2)
            tittel_full = serie_tittel

        # Forsidebilete
        cover_url = b.get("cover", {}).get("medium", "")

        return {
            "tittel":      tittel_full,
            "forfatter":   forfattar,
            "serie":       serie_tittel,
            "nummer":      serie_nummer,
            "shelf":       forkortelse,
            "kategori":    "Engelsk Vaksen",
            "malfom":      "Engelsk",
            "emne":        "",
            "er_sakprosa": False,
            "er_biletbok": False,
            "dewey":       "",
            "språk":       "eng",
            "alder_kode":  "a",
            "cover_url":   cover_url,
            "kjelde":      "openlibrary",  # Markerer at data er frå Open Library
        }
    except Exception:
        return None

def marc_field(record, tag, subfield=None):
    for df in record.findall(f"{{{MNS}}}datafield[@tag='{tag}']"):
        if subfield:
            sf = df.find(f"{{{MNS}}}subfield[@code='{subfield}']")
            if sf is not None and sf.text:
                return sf.text.strip()
        else:
            return df
    return ""

def marc_fields(record, tag, subfield):
    result = []
    for df in record.findall(f"{{{MNS}}}datafield[@tag='{tag}']"):
        for sf in df.findall(f"{{{MNS}}}subfield[@code='{subfield}']"):
            if sf.text:
                result.append(sf.text.strip())
    return result

def poster_i_svar(xml_text: str) -> list:
    """Alle MARC-postane i eit SRU-svar frå Ája."""
    root = ET.fromstring(xml_text)
    poster = []
    for r in root.findall(".//srw:record", NS):
        rec = r.find(f".//{{{MNS}}}record")
        if rec is not None:
            poster.append(rec)
    return poster

def parse_mods(xml_text: str) -> dict | None:
    """Tolk den første posten i eit SRU-svar."""
    poster = poster_i_svar(xml_text)
    return parse_post(poster[0]) if poster else None

def parse_post(rec) -> dict:
    """Hent ut etikettfelta frå éin MARC-post."""
    # Tittel (245$a)
    tittel = marc_field(rec, "245", "a").rstrip(" /")

    # Forfatter (100$a)
    forfatter = marc_field(rec, "100", "a").rstrip(",")

    # Hylleplassering (852$h+$i eller berre $i)
    # 852$i = hyllekode (t.d. HAA), 852$h = klassifikasjon (t.d. 796.334092)
    # Vi lagrar begge, men viser berre $i i GUI
    shelf = ""
    shelf_display = ""
    for df in rec.findall(f"{{{MNS}}}datafield[@tag='852']"):
        sf_h = df.find(f"{{{MNS}}}subfield[@code='h']")
        sf_i = df.find(f"{{{MNS}}}subfield[@code='i']")
        if sf_i is not None and sf_i.text:
            shelf_display = sf_i.text.strip()  # Berre hyllekoden
        if sf_h is not None and sf_h.text:
            h_val = sf_h.text.strip()
            if shelf_display:
                shelf = f"{h_val} {shelf_display}"  # Full verdi for etiketten
            else:
                shelf = h_val
        elif shelf_display:
            shelf = shelf_display
        if shelf:
            break

    # Serie (490$a+$v, fallback 830$a+$v)
    serie_tittel = marc_field(rec, "490", "a").rstrip(" /") or marc_field(rec, "830", "a").rstrip(" /")
    serie_nummer = marc_field(rec, "490", "v") or marc_field(rec, "830", "v")

    # Dewey (082$a) – full for oppslag, avkorta for visning
    dewey_full = marc_field(rec, "082", "a")
    dewey = ""
    if dewey_full:
        parts = dewey_full.split(".")
        if len(parts) > 1:
            dewey = parts[0] + "." + parts[1][:2]
        else:
            dewey = parts[0]
        if "." in dewey:
            dewey = dewey.rstrip("0").rstrip(".")

    # 008-felt
    cf008 = ""
    for cf in rec.findall(f"{{{MNS}}}controlfield[@tag='008']"):
        if cf.text:
            cf008 = cf.text

    # Språk (041$a eller 008 pos 35-37)
    språk_kode = marc_field(rec, "041", "a")
    if not språk_kode and len(cf008) > 37:
        språk_kode = cf008[35:38].strip()

    # Alderskode: 019$a har bu, mu, vu, u osv.
    alder_kode = ""
    kode_019 = marc_field(rec, "019", "a")
    if kode_019:
        kodar = [k.strip() for k in kode_019.lower().split(",")]
        for k in ["mu", "vu", "bu", "u"]:
            if k in kodar:
                alder_kode = k
                break
        if not alder_kode:
            for k in ["b", "j", "a"]:
                if k in kodar:
                    alder_kode = "b" if k == "j" else k
                    break
    if not alder_kode and len(cf008) > 22:
        audience_map = {"j": "b", "d": "u", "a": "a", "e": "a"}
        alder_kode = audience_map.get(cf008[22], "")

    # Forsidebilete (856$u der $3 = Omslagsbilde)
    cover_url = ""
    for df in rec.findall(f"{{{MNS}}}datafield[@tag='856']"):
        sf3 = df.find(f"{{{MNS}}}subfield[@code='3']")
        if sf3 is not None and "omslagsbilde" in (sf3.text or "").lower():
            sfu = df.find(f"{{{MNS}}}subfield[@code='u']")
            if sfu is not None and sfu.text:
                cover_url = sfu.text.strip()
                break

    # Innbinding (020$q) - t.d. "kartonert" for pekebøker
    innbinding = marc_field(rec, "020", "q").lower()

    # Sjangrar (655$a)
    sjangrar = marc_fields(rec, "655", "a")

    # Er sakprosa?
    er_sakprosa = False
    if dewey_full:
        try:
            dewey_num = float(dewey_full.replace(",", ".").split()[0])
            er_sakprosa = not (800 <= dewey_num < 900)
        except:
            pass
    if er_litteraturhistorie(dewey_full):
        er_sakprosa = True   # bøker OM litteratur skal ha emne, ikkje skjønnlitt-kategori

    # Override: manga, teikneserie, biletbøker, lettlest = skjønnlitteratur
    sjangrar_lower = [s.lower() for s in sjangrar]
    if any("manga" in s or "teikneserie" in s or "tegneserie" in s
           or "bildebok" in s or "biletbok" in s or "bildebøker" in s
           or "biletbøker" in s or "lettlest" in s or "lettlesen" in s
           for s in sjangrar_lower):
        er_sakprosa = False

    # Emneord
    dewey_emne = dewey_til_emneord(dewey_full or dewey)
    if dewey_emne:
        emne_forslag = dewey_emne
    else:
        emneord = marc_fields(rec, "650", "a")
        emneord_unike = list(dict.fromkeys(emneord))
        emne_forslag = min(emneord_unike, key=len) if emneord_unike else ""

    alder = aldersgruppe(alder_kode)
    kategori = bestem_kategori(sjangrar, alder, språk_kode, er_sakprosa)

    # Bestem biletbok-type (tekst øvst på etiketten)
    biletbok_type = "Biletbøker"
    if innbinding == "kartonert":
        biletbok_type = "Peikebøker"
        kategori = "biletbøker"
    else:
        sjangrar_lower2 = [s.lower() for s in sjangrar]
        if any("myldre" in s for s in sjangrar_lower2):
            biletbok_type = "Myldrebøker"

    return {
        "tittel":      tittel,
        "forfatter":   forfatter,
        "serie":       serie_tittel,
        "nummer":      serie_nummer,
        "shelf":       shelf_display or shelf,  # Vis berre hyllekode i GUI
        "cover_url":   cover_url,
        "kategori":    kategori,
        "malfom":      malfom_tekst(språk_kode),
        "emne":        emne_forslag,
        "er_sakprosa": er_sakprosa,
        "er_biletbok": kategori == "biletbøker",
        "biletbok_type": biletbok_type,
        "dewey":       dewey,
        "språk":       språk_kode,
        "alder_kode":  alder_kode,
    }

# ── Dymo-fil-generering ──────────────────────────────────────────────────────

def set_text(root, name, text):
    """Set tekst i eit TextObject med gjeve namn."""
    for obj in root.iter("TextObject"):
        n = obj.find("Name")
        if n is not None and n.text == name:
            for span in obj.iter("TextSpan"):
                t = span.find("Text")
                if t is not None:
                    t.text = text
                    return


def set_fontsize(root, name, size):
    """Set skriftstorleik på eit TextObject."""
    for obj in root.iter("TextObject"):
        n = obj.find("Name")
        if n is not None and n.text == name:
            for fs in obj.iter("FontSize"):
                fs.text = str(size)
            return

def fjern_objekt(root, name):
    """Fjern eit objekt heilt frå XML (Dymo støttar ikkje Visibility-element)."""
    tags = ["TextObject", "ShapeObject", "LineObject"]
    for tag in tags:
        for parent in root.iter():
            for obj in list(parent):
                if obj.tag == tag:
                    n = obj.find("Name")
                    if n is not None and n.text == name:
                        parent.remove(obj)
                        return

def generer_dymo(bok: dict) -> str:
    """Generer .dymo-fil og returner XML-streng."""
    er_biletbok = bok.get("er_biletbok") or bok.get("kategori", "").lower() == "biletbøker"

    if er_biletbok:
        tmpl = ET.parse(BILETBOK_TMPL)
        root = tmpl.getroot()
        # Tekst øvst: Biletbøker / Myldrebøker / Peikebok
        biletbok_type = bok.get("biletbok_type", "Biletbøker")
        set_text(root, "TextObject0", biletbok_type)
        # Stor bokstav = første bokstav i etternamnet
        forfatter = bok.get("forfatter", "")
        tittel = bok.get("tittel", "")
        if forfatter:
            bokstav = forfatter[0].upper()
        elif tittel:
            bokstav = tittel[0].upper()
        else:
            bokstav = "?"
        set_text(root, "TextObject1", bokstav)
        set_text(root, "TextObject2", bok.get("malfom", "Bokmål"))
    else:
        tmpl = ET.parse(STANDARD_TMPL)
        root = tmpl.getroot()
        er_sakprosa = bok.get("er_sakprosa", False)
        # Viss kategori er sett til ein skjønnlitterær kategori, overstyrer vi sakprosa
        kat = bok.get("kategori", "").lower()
        skjonnlitt_kategoriar = [
            "fantasy", "kriminal", "roman", "grøssar", "thriller",
            "teikneserie", "manga", "humor", "lyrikk", "skodespel",
            "noveller", "engelsk", "barnebøker", "lettlest", "biletbøker"
        ]
        if any(k in kat for k in skjonnlitt_kategoriar):
            er_sakprosa = False

        # Serietittel – fjern heilt viss tom
        serie = bok.get("serie", "")
        if serie:
            set_text(root, "TextObject4", serie)
        else:
            fjern_objekt(root, "TextObject4")

        # Serienummer + sirkel – fjern viss tomt
        nummer = bok.get("nummer", "")
        if nummer:
            set_text(root, "TextObject3", nummer)
        else:
            fjern_objekt(root, "TextObject3")
            fjern_objekt(root, "ShapeObject0")

        # Sjanger (skjønnlitt.) eller tema (sakprosa)
        if er_sakprosa:
            emne = bok.get("emne", "")
            # Avkorta tema til maks 18 teikn så det får plass på etiketten
            if emne:
                set_text(root, "TextObject0", emne)
                kat_fs = 12 if len(emne) <= 12 else 10 if len(emne) <= 16 else 8
                set_fontsize(root, "TextObject0", kat_fs)
            else:
                fjern_objekt(root, "TextObject0")
            dewey = bok.get("dewey", "")
            shelf = bok.get("shelf", "").strip()
            # Ája returnerer av og til "641.82 FOL" eller "796.3340946 MUG" som shelf
            # Sjekk om shelf startar med eit dewey-liknande prefiks (tal + punktum)
            shelf_har_dewey = bool(re.match(r'^q?[\s]*[0-9]+[.]?[0-9]*[\s]+[A-Za-z]', shelf))
            if shelf_har_dewey:
                # Shelf inneheld allereie dewey - trekk ut berre hyllekoden (siste ord)
                # og set saman med avkorta dewey
                hyllekode = shelf.split()[-1]
                tekst1 = f"{dewey} {hyllekode}" if dewey else hyllekode
            else:
                tekst1 = f"{dewey} {shelf}" if dewey and shelf else dewey or shelf
            set_text(root, "TextObject1", tekst1)
            # Skriftstorleik basert på lengde, maks 16
            fs = 16 if len(tekst1) <= 8 else 14 if len(tekst1) <= 11 else 12
            set_fontsize(root, "TextObject1", fs)
        else:
            kategori = bok.get("kategori", "")
            set_text(root, "TextObject0", kategori)
            kat_fs = 12 if len(kategori) <= 12 else 10 if len(kategori) <= 16 else 8
            set_fontsize(root, "TextObject0", kat_fs)
            # Bruk shelf direkte (ikkje forkortelse som kan innehalda dewey+shelf)
            shelf = bok.get("shelf", "").strip()
            set_text(root, "TextObject1", shelf)
            fs = 16 if len(shelf) <= 4 else 14 if len(shelf) <= 6 else 12
            set_fontsize(root, "TextObject1", fs)

        # Målform
        set_text(root, "TextObject2", bok.get("malfom", "Bokmål"))

    return som_xml(tmpl)


def som_xml(tmpl) -> str:
    """Skriv eit utfylt malobjekt ut som XML-tekst (same format som .dymo-filene)."""
    fd, tmp = tempfile.mkstemp(suffix=".dymo")
    os.close(fd)
    try:
        tmpl.write(tmp, encoding="utf-8", xml_declaration=True)
        with open(tmp, encoding="utf-8") as f:
            return f.read()
    finally:
        os.unlink(tmp)


# ── Utskrift ─────────────────────────────────────────────────────────────────
DYMO_CONNECT_EXE = r"C:\Program Files (x86)\DYMO\DYMO Connect\DYMOConnect.exe"

def _skriv_ut_direkte(dymo_xml: str, printer_name: str, rull: str) -> tuple[bool, str]:
    """Prøv dymo-sdk fyrst, fell tilbake til Dymo Connect med Ctrl+P."""
    tmp = os.path.join(tempfile.gettempdir(), "boketikett_print.dymo")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(dymo_xml)

    # Metode 1: dymo-sdk (stille utskrift utan GUI)
    sdk_feil = ""
    try:
        import dymo_sdk as dsdk
        time.sleep(1)  # Gi SDK tid til å initialisera
        label = dsdk.DymoLabel()
        label.load_label_from_file(tmp)
        for p in dsdk.get_printers():
            if p.is_connected and ("DYMO" in str(p.name).upper() or
                                   printer_name.lower() in str(p.name).lower()):
                # roll_selected: 0=auto, 1=venstre, 2=høgre
                p.print_label(label, roll_selected=2 if rull == "Right" else 1)
                return True, "Sendt til skrivar"
        raise RuntimeError("Ingen tilkopla skrivar funne")
    except ImportError:
        sdk_feil = "dymo-sdk er ikkje installert"
    except Exception as e:
        sdk_feil = f"dymo-sdk feila: {e}"

    # Metode 2: opna Dymo Connect og trykk Ctrl+P (reserve)
    if not os.path.exists(DYMO_CONNECT_EXE):
        return False, f"{sdk_feil}. Fann heller ikkje Dymo Connect."
    try:
        subprocess.Popen([DYMO_CONNECT_EXE, tmp])
        try:
            import pyautogui
            time.sleep(4)
            pyautogui.hotkey("ctrl", "p")
            time.sleep(1)
            pyautogui.press("enter")
        except ImportError:
            return True, f"{sdk_feil}. Opna Dymo Connect – trykk Ctrl+P sjølv."
        return True, f"{sdk_feil}. Skreiv ut via Dymo Connect."
    except Exception as e:
        return False, f"{sdk_feil}. Utskriftsfeil: {e}"


# All utskrift går gjennom éin og same tråd, i rett rekkjefølgje. Då kjem
# ikkje to utskrifter i konflikt, og dymo-sdk ser alltid same tråd.
_utskriftskø: "queue.Queue" = queue.Queue()

def _utskriftstråd():
    try:
        import pythoncom  # finst viss pywin32 er installert
        pythoncom.CoInitialize()
    except Exception:
        pass
    while True:
        jobb, svar = _utskriftskø.get()
        try:
            svar.put(_skriv_ut_direkte(*jobb))
        except Exception as e:
            svar.put((False, f"Utskriftsfeil: {e}"))

threading.Thread(target=_utskriftstråd, daemon=True, name="utskrift").start()

def skriv_ut(dymo_xml: str, printer_name: str, rull: str = "Right") -> tuple[bool, str]:
    """Legg ein etikett i utskriftskøen og vent på resultatet."""
    svar: "queue.Queue" = queue.Queue(maxsize=1)
    _utskriftskø.put(((dymo_xml, printer_name, rull), svar))
    return svar.get(timeout=120)


# ── Tittelsøk ────────────────────────────────────────────────────────────────
def sok_tittel(tittel: str, maks: int = 10) -> list:
    """Søk i Ája på tittel og returner ferdig tolka bøker."""
    url = (f"https://sru.aja.bs.no/mlnb"
           f"?operation=searchRetrieve"
           f"&query=dc.title=%22{requests.utils.quote(tittel)}%22"
           f"&recordSchema=marc21nor&maximumRecords={maks}")
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    bøker = []
    for rec in poster_i_svar(r.text):
        bok = parse_post(rec)
        bok["kjelde"] = "aja"
        bok["isbn"] = re.sub(r"[\s-]", "", marc_field(rec, "020", "a").split(" ")[0])
        bøker.append(bok)
    return bøker

ALLE_KATEGORIAR = sorted([
    "Fantasy Barn", "Fantasy Ungdom", "Fantasy Vaksen",
    "Kriminal Barn", "Kriminal Ungdom", "Kriminal Vaksen",
    "Barnebøker", "Lettlest Barn", "Roman Ungdom", "Roman Vaksen",
    "Grøssar Barn", "Grøssar Ungdom", "Grøssar Vaksen",
    "Teikneserie Barn", "Teikneserie Vaksen",
    "Manga Barn", "Manga Ungdom", "Manga Vaksen",
    "Humor Barn",
    "Lyrikk Barn", "Lyrikk Ungdom", "Lyrikk Vaksen",
    "Noveller Vaksen",
    "Skodespel Barn", "Skodespel Ungdom", "Skodespel Vaksen",
    "Engelsk Barn", "Engelsk Ungdom", "Engelsk Vaksen",
    "biletbøker",
])
MALFOMER = ["Bokmål", "Nynorsk", "Engelsk"]

KAT_FARGAR = {
    "fantasy":     "#7c3aed",
    "kriminal":    "#dc2626",
    "roman":       "#2563eb",
    "grøssar":     "#065f46",
    "teikneserie": "#d97706",
    "manga":       "#db2777",
    "humor":       "#d97706",
    "lyrikk":      "#0891b2",
    "noveller":    "#0d9488",
    "skodespel":   "#7c3aed",
    "engelsk":     "#1d4ed8",
    "barnebøker":  "#059669",
    "lettlest":    "#059669",
    "biletbøker":  "#b45309",
}

def hent_serie(forfatter: str, serie: str, aktiv_isbn: str) -> list:
    """Hentar alle bøker i ein serie via forfattarsøk."""
    if not forfatter:
        return []
    etternamn = forfatter.split(",")[0].strip()
    url = (f"https://sru.aja.bs.no/mlnb"
           f"?operation=searchRetrieve"
           f"&query=dc.creator%3D%22{requests.utils.quote(etternamn)}%22"
           f"&recordSchema=marc21nor&maximumRecords=100")
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        bøker = []
        sette = set()
        for rec_el in root.findall(".//srw:record", NS):
            rec = rec_el.find(f".//{{{MNS}}}record")
            if rec is None:
                continue
            # Filtrer bort e-bøker og lydbøker
            cf007 = ""
            for cf in rec.findall(f"{{{MNS}}}controlfield[@tag='007']"):
                if cf.text:
                    cf007 = cf.text
            if cf007 and not cf007.startswith("t"):
                continue
            # Sjekk serie
            serie_felt = ""
            serie_nr = ""
            for df in rec.findall(f"{{{MNS}}}datafield[@tag='490']"):
                sf_a = df.find(f"{{{MNS}}}subfield[@code='a']")
                sf_v = df.find(f"{{{MNS}}}subfield[@code='v']")
                if sf_a is not None and sf_a.text:
                    serie_felt = sf_a.text.strip().rstrip(" /")
                if sf_v is not None and sf_v.text:
                    serie_nr = sf_v.text.strip()
            if not serie_felt or serie_felt.lower() != serie.lower():
                continue
            # Tittel
            tittel = ""
            for df in rec.findall(f"{{{MNS}}}datafield[@tag='245']"):
                sf = df.find(f"{{{MNS}}}subfield[@code='a']")
                if sf is not None and sf.text:
                    tittel = sf.text.strip().rstrip(" /")
            # ISBN
            isbn = ""
            for df in rec.findall(f"{{{MNS}}}datafield[@tag='020']"):
                sf = df.find(f"{{{MNS}}}subfield[@code='a']")
                if sf is not None and sf.text:
                    isbn = sf.text.strip()
            # Unngå duplikat (same tittel + nr)
            key = f"{serie_nr}_{tittel}"
            if key in sette:
                continue
            sette.add(key)
            bøker.append({
                "tittel": tittel,
                "nummer": serie_nr,
                "isbn": isbn,
            })
        # Sorter etter serienummer
        def sorter_nr(b):
            try:
                return float(b.get("nummer", "0") or "0")
            except:
                return 0
        bøker.sort(key=sorter_nr)
        return bøker
    except Exception:
        return []


def set_bold(root, name: str, bold: bool):
    """Set IsBold on a TextObject."""
    for obj in root.iter("TextObject"):
        n = obj.find("Name")
        if n is not None and n.text == name:
            for ib in obj.iter("IsBold"):
                ib.text = "True" if bold else "False"

def generer_serieliste_dymo(serie: str, linjer: list, aktiv_idx: int = -1) -> str:
    """Genererer ein serieliste-etikett med Serieliste.dymo-malen.
    aktiv_idx: indeks i linjer-lista som skal uthevast (bold), -1 = ingen.
    """
    tmpl = ET.parse(SERIELISTE_TMPL)
    root = tmpl.getroot()

    # Fyll inn linjefelt 1-5
    for i in range(5):
        tekst = linjer[i] if i < len(linjer) else ""
        set_text(root, f"TextObject{i+1}", tekst)
        set_bold(root, f"TextObject{i+1}", i == aktiv_idx)

    return som_xml(tmpl)
