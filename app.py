"""
Boketikett-generator for Dymo LabelWriter 450 Twin Turbo
=========================================================
- Scan/skriv inn ISBN
- Automatisk oppslag i Ája SRU (Biblioteksentralen)
- Genererer ekte .dymo-filer og skriv ut via Dymo Connect
"""

from tkinter import messagebox
import os, re, json, tempfile, requests, subprocess
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
DYMO_PRINT_URL  = "https://127.0.0.1:41951/DYMO/DLS/Printing/PrintLabel"

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

# ── Forkortelse ──────────────────────────────────────────────────────────────

# ── Ája SRU-oppslag ──────────────────────────────────────────────────────────
NS = {
    "srw":  "http://www.loc.gov/zing/srw/",
    "mods": "http://www.loc.gov/mods/v3",
}

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
    MNS = "info:lc/xmlns/marcxchange-v1"
    for df in record.findall(f"{{{MNS}}}datafield[@tag='{tag}']"):
        if subfield:
            sf = df.find(f"{{{MNS}}}subfield[@code='{subfield}']")
            if sf is not None and sf.text:
                return sf.text.strip()
        else:
            return df
    return ""

def marc_fields(record, tag, subfield):
    MNS = "info:lc/xmlns/marcxchange-v1"
    result = []
    for df in record.findall(f"{{{MNS}}}datafield[@tag='{tag}']"):
        for sf in df.findall(f"{{{MNS}}}subfield[@code='{subfield}']"):
            if sf.text:
                result.append(sf.text.strip())
    return result

def parse_mods(xml_text: str) -> dict | None:
    root = ET.fromstring(xml_text)
    records = root.findall(".//srw:record", NS)
    if not records:
        return None
    MNS = "info:lc/xmlns/marcxchange-v1"
    rec = records[0].find(f".//{{{MNS}}}record")
    if rec is None:
        return None

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
    MNS2 = "info:lc/xmlns/marcxchange-v1"
    for df in rec.findall(f"{{{MNS2}}}datafield[@tag='856']"):
        sf3 = df.find(f"{{{MNS2}}}subfield[@code='3']")
        if sf3 is not None and "omslagsbilde" in (sf3.text or "").lower():
            sfu = df.find(f"{{{MNS2}}}subfield[@code='u']")
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

    # Returner XML
    ET.register_namespace("", "")
    tmp = tempfile.mktemp(suffix=".dymo")
    tmpl.write(tmp, encoding="utf-8", xml_declaration=True)
    with open(tmp, "r", encoding="utf-8") as f:
        content = f.read()
    os.unlink(tmp)
    return content

DYMO_DIR         = r"C:\Program Files (x86)\DYMO\DYMO Connect"
DYMO_CONNECT_EXE = os.path.join(DYMO_DIR, "DYMOConnect.exe")

def skriv_ut(dymo_xml: str, printer_name: str, rull: str = "Right") -> bool:
    """Prøv dymo-sdk fyrst, fell tilbake til Dymo Connect med Ctrl+P."""
    tmp = os.path.join(tempfile.gettempdir(), "boketikett_print.dymo")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(dymo_xml)

    # Metode 1: dymo-sdk (stille utskrift utan GUI)
    try:
        import dymo_sdk as dsdk
        import time as _time
        _time.sleep(1)  # Gi SDK tid til å initialisera
        label = dsdk.DymoLabel()
        label.load_label_from_file(tmp)
        printers = dsdk.get_printers()
        for p in printers:
            if p.is_connected and ("DYMO" in str(p.name).upper() or
                                   printer_name.lower() in str(p.name).lower()):
                # roll_selected: 0=auto, 1=venstre, 2=høgre
                roll_num = 2 if rull == "Right" else 1
                p.print_label(label, roll_selected=roll_num)
                return True
        raise RuntimeError("Ingen tilkopla skrivar funne")
    except ImportError:
        pass
    except Exception as sdk_err:
        messagebox.showwarning("dymo-sdk", f"SDK feila (prøver fallback):\n{sdk_err}")

    # Metode 2: Opna Dymo Connect med Ctrl+P (fallback)
    try:
        import time
        if not os.path.exists(DYMO_CONNECT_EXE):
            messagebox.showerror("Feil", f"Fann ikkje:\n{DYMO_CONNECT_EXE}")
            return False
        subprocess.Popen([DYMO_CONNECT_EXE, tmp])
        try:
            import pyautogui
            time.sleep(4)
            pyautogui.hotkey("ctrl", "p")
            time.sleep(1)
            pyautogui.press("enter")
        except ImportError:
            pass
        return True
    except Exception as e:
        messagebox.showerror("Utskriftsfeil", str(e))
# ── GUI ──────────────────────────────────────────────────────────────────────

import threading, io
import customtkinter as ctk

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

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

def kat_farge(kat: str) -> str:
    for k, c in KAT_FARGAR.items():
        if k in kat.lower():
            return c
    return "#4a5568"

def _hent_serie(forfatter: str, serie: str, aktiv_isbn: str) -> list:
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
        SRW = "http://www.loc.gov/zing/srw/"
        MNS = "info:lc/xmlns/marcxchange-v1"
        bøker = []
        sette = set()
        for rec_el in root.findall(f".//{{{SRW}}}record"):
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


def _set_bold(root, name: str, bold: bool):
    """Set IsBold on a TextObject."""
    for obj in root.iter("TextObject"):
        n = obj.find("Name")
        if n is not None and n.text == name:
            for ib in obj.iter("IsBold"):
                ib.text = "True" if bold else "False"

def _generer_serieliste_dymo(serie: str, linjer: list, aktiv_idx: int = -1) -> str:
    """Genererer ein serieliste-etikett med Serieliste.dymo-malen.
    aktiv_idx: indeks i linjer-lista som skal uthevast (bold), -1 = ingen.
    """
    tmpl = ET.parse(SERIELISTE_TMPL)
    root = tmpl.getroot()

    # Fyll inn linjefelt 1-5
    for i in range(5):
        tekst = linjer[i] if i < len(linjer) else ""
        set_text(root, f"TextObject{i+1}", tekst)
        _set_bold(root, f"TextObject{i+1}", i == aktiv_idx)

    ET.register_namespace("", "")
    tmp = tempfile.mktemp(suffix=".dymo")
    tmpl.write(tmp, encoding="utf-8", xml_declaration=True)
    with open(tmp, encoding="utf-8") as f:
        return f.read()


# Alias for skriv_ut inside dialog (avoids name clash)
def skriv_ut_fn(dymo_xml: str, printer_name: str) -> bool:
    return skriv_ut(dymo_xml, printer_name)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Boketikett-generator")
        self.geometry("1000x720")
        self.minsize(900, 650)
        self.settings = load_settings()
        self.books = []
        self.current_index = -1
        self._cover_photo = None
        self._build_ui()
        self.bind("<Control-Return>", lambda e: self._skriv_ut_ein())
        self.bind("<Delete>",         lambda e: self._fjern())

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Header ──
        hdr = ctk.CTkFrame(self, corner_radius=0, fg_color="#1a56db", height=56)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(hdr, text="Boketikett-generator",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color="white").grid(row=0, column=0, padx=20, pady=14)
        self.teller_var = ctk.StringVar(value="")
        ctk.CTkLabel(hdr, textvariable=self.teller_var,
                     font=ctk.CTkFont(size=12),
                     text_color="white").grid(row=0, column=2, padx=20)

        # ── Hovudområde ──
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=1, column=0, sticky="nsew", padx=16, pady=12)
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)

        # ── Venstre panel ──
        left = ctk.CTkFrame(main, corner_radius=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_rowconfigure(2, weight=1)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="1.  Scan / skriv inn ISBN",
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
                         row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        isbn_frame = ctk.CTkFrame(left, fg_color="transparent")
        isbn_frame.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="ew")
        isbn_frame.grid_columnconfigure(0, weight=1)

        self.isbn_var = ctk.StringVar()
        self.isbn_entry = ctk.CTkEntry(isbn_frame, textvariable=self.isbn_var,
                                       font=ctk.CTkFont(size=14),
                                       height=40, corner_radius=8,
                                       placeholder_text="Scan ISBN eller skriv tittel...")
        self.isbn_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.isbn_entry.bind("<Return>", lambda e: self._legg_til_isbn())
        self.isbn_entry.focus()

        self.legg_til_btn = ctk.CTkButton(isbn_frame, text="Legg til",
                                          width=90, height=40,
                                          corner_radius=8,
                                          font=ctk.CTkFont(size=13, weight="bold"),
                                          command=self._legg_til_isbn)
        self.legg_til_btn.grid(row=0, column=1)

        self.spinner_var = ctk.StringVar(value="")
        ctk.CTkLabel(isbn_frame, textvariable=self.spinner_var,
                     font=ctk.CTkFont(size=13)).grid(row=1, column=0, pady=(4, 0))

        # Bokliste
        self.book_list = ctk.CTkScrollableFrame(left, label_text="Bøker i lista",
                                                corner_radius=8)
        self.book_list.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.book_list.grid_columnconfigure(0, weight=1)
        self._list_buttons = []

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.grid(row=3, column=0, padx=16, pady=(0, 16), sticky="ew")
        btn_row.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(btn_row, text="Fjern vald", fg_color="#e53e3e",
                      hover_color="#c53030", corner_radius=8,
                      height=36, command=self._fjern).grid(
                          row=0, column=0, padx=(0, 8))

        ctk.CTkButton(btn_row, text="Serieliste", fg_color="#6d28d9",
                      hover_color="#5b21b6", corner_radius=8,
                      height=36, command=self._serieliste).grid(
                          row=0, column=1, sticky="ew")

        # ── Høgre panel ──
        right = ctk.CTkFrame(main, corner_radius=12)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="2.  Kontroller / rediger",
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
                         row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        # Forsidebilete + mal-indikator
        top_right = ctk.CTkFrame(right, fg_color="transparent")
        top_right.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="ew")
        top_right.grid_columnconfigure(1, weight=1)

        self.cover_frame = ctk.CTkFrame(top_right, width=90, height=130,
                                        corner_radius=8)
        self.cover_frame.grid(row=0, column=0, padx=(0, 12))
        self.cover_frame.grid_propagate(False)
        self.cover_label_var = ctk.StringVar(value="")
        self.cover_ctk_label = ctk.CTkLabel(self.cover_frame, text="",
                                             font=ctk.CTkFont(size=28))
        self.cover_ctk_label.place(relx=0.5, rely=0.5, anchor="center")

        info_frame = ctk.CTkFrame(top_right, fg_color="transparent")
        info_frame.grid(row=0, column=1, sticky="ew")
        info_frame.grid_columnconfigure(0, weight=1)

        self.mal_var = ctk.StringVar(value="")
        self.mal_label = ctk.CTkLabel(info_frame, textvariable=self.mal_var,
                                      font=ctk.CTkFont(size=11, slant="italic"),
                                      fg_color="#38a169", corner_radius=6,
                                      height=32)
        self.mal_label.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.kat_badge = ctk.CTkLabel(info_frame, text="",
                                      font=ctk.CTkFont(size=11, weight="bold"),
                                      fg_color="#4a5568", corner_radius=6,
                                      height=32)
        self.kat_badge.grid(row=1, column=0, sticky="ew")

        # Skjema-felt
        fields = [
            ("Tittel:",          "tittel",   None),
            ("Forfatter:",       "forfatter", None),
            ("Hyllekode:",       "shelf",    None),
            ("Dewey:",           "dewey",    None),
            ("Kategori:",        "kategori", ALLE_KATEGORIAR),
            ("Emne (sakprosa):", "emne",     None),
            ("Serienavn:",       "serie",    None),
            ("Nummer i serie:",  "nummer",   None),
            ("Målform:",         "malfom",   MALFOMER),
        ]
        self.vars = {}
        form = ctk.CTkScrollableFrame(right, fg_color="transparent", height=320)
        form.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 8))
        form.grid_columnconfigure(1, weight=1)

        for i, (label, key, choices) in enumerate(fields):
            ctk.CTkLabel(form, text=label, anchor="w",
                         font=ctk.CTkFont(size=11),
                         text_color="gray").grid(
                             row=i, column=0, sticky="w", padx=(0, 8), pady=3)
            var = ctk.StringVar()
            self.vars[key] = var
            if choices:
                w = ctk.CTkComboBox(form, variable=var, values=choices,
                                    width=220, height=32, corner_radius=6,
                                    command=lambda v, k=key: self._on_combo(k, v))
                w.grid(row=i, column=1, sticky="ew", pady=3)
                if key == "kategori":
                    var.trace_add("write", lambda *a: self._oppdater_mal())
            else:
                w = ctk.CTkEntry(form, textvariable=var,
                                 height=32, corner_radius=6)
                w.grid(row=i, column=1, sticky="ew", pady=3)

        # Knapper
        btn_frame = ctk.CTkFrame(right, fg_color="transparent")
        btn_frame.grid(row=3, column=0, padx=16, pady=(0, 8))

        ctk.CTkButton(btn_frame, text="Lagre endringar",
                      width=150, height=36, corner_radius=8,
                      fg_color="#3182ce", hover_color="#2b6cb0",
                      command=self._lagre).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_frame, text="Skriv ut denne",
                      width=150, height=36, corner_radius=8,
                      fg_color="#dd6b20", hover_color="#c05621",
                      command=self._skriv_ut_ein).pack(side="left")

        ctk.CTkLabel(right,
                     text="Ctrl+Enter = skriv ut denne   Del = fjern",
                     font=ctk.CTkFont(size=9), text_color="gray").grid(
                         row=4, column=0, pady=(0, 8))

        right.grid_rowconfigure(2, weight=1)

        # ── Botn ──
        bot = ctk.CTkFrame(self, corner_radius=0, height=80)
        bot.grid(row=2, column=0, sticky="ew")
        bot.grid_propagate(False)
        bot.grid_columnconfigure(1, weight=1)

        pr_frame = ctk.CTkFrame(bot, fg_color="transparent")
        pr_frame.grid(row=0, column=0, padx=16, pady=10, sticky="w")

        ctk.CTkLabel(pr_frame, text="Skrivar:",
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 8))
        self.printer_var = ctk.StringVar(
            value=self.settings.get("printer", "DYMO LabelWriter 450 TwinTurbo"))
        ctk.CTkEntry(pr_frame, textvariable=self.printer_var,
                     width=280, height=32, corner_radius=6).pack(side="left", padx=(0, 8))
        ctk.CTkButton(pr_frame, text="Lagre", width=70, height=32,
                      corner_radius=6, fg_color="#718096", hover_color="#4a5568",
                      command=self._lagre_skriver).pack(side="left")

        ctk.CTkButton(bot, text="Skriv ut ALLE etiketter",
                      height=44, corner_radius=8,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color="#e53e3e", hover_color="#c53030",
                      command=self._skriv_ut_alle).grid(
                          row=0, column=2, padx=16, pady=10)

        # ── Statuslinje ──
        self.status_var = ctk.StringVar(value="Klar. Scan eller skriv inn ISBN og trykk Enter.")
        ctk.CTkLabel(self, textvariable=self.status_var,
                     font=ctk.CTkFont(size=10),
                     anchor="w", height=28).grid(
                         row=3, column=0, sticky="ew", padx=16, pady=(0, 4))

    def _on_combo(self, key, value):
        if key == "kategori":
            self._oppdater_mal()

    def _legg_til_isbn(self):
        tekst = self.isbn_var.get().strip()
        if not tekst:
            return
        self.isbn_var.set("")
        # Sjekk om det er ISBN (berre siffer, evt. bindestrekar) eller tittel
        isbn_rein = re.sub(r"[\s-]", "", tekst)
        if isbn_rein.isdigit() and len(isbn_rein) in (10, 13):
            # ISBN-søk
            self.status_var.set(f"Slår opp {tekst}...")
            self.spinner_var.set("Hentar data...")
            self.update()
            try:
                bok = aja_oppslag(isbn_rein)
                if not bok:
                    self.status_var.set(f"Ikkje funne: {tekst}. Legg til manuelt.")
                    bok = {"tittel": "", "forfatter": "", "shelf": "", "dewey": "",
                           "kategori": "", "emne": "", "serie": "", "nummer": "",
                           "malfom": "Bokmål", "er_sakprosa": False,
                           "er_biletbok": False, "kjelde": "manuell"}
                else:
                    kjelde = bok.get("kjelde", "aja")
                    if kjelde == "openlibrary":
                        self.status_var.set(f"Henta frå Open Library: {bok.get('tittel', tekst)}")
                    else:
                        self.status_var.set(f"Lagt til: {bok.get('tittel', tekst)}")
                bok["isbn"] = isbn_rein
                self.books.append(bok)
                self._refresh_list()
                idx = len(self.books) - 1
                self._select_book(idx)
            except Exception as e:
                self.status_var.set(f"Feil: {e}")
                messagebox.showerror("Oppslag feila", str(e))
            finally:
                self.spinner_var.set("")
            return
        # Tittel-søk
        self._tittel_sok(tekst)

    def _tittel_sok(self, tittel: str):
        tittel = tittel.strip()
        if not tittel:
            return
        self.status_var.set(f"Søkjer etter '{tittel}'...")
        self.spinner_var.set("Hentar data...")
        self.update()
        try:
            url = (f"https://sru.aja.bs.no/mlnb"
                   f"?operation=searchRetrieve"
                   f"&query=dc.title=%22{requests.utils.quote(tittel)}%22"
                   f"&recordSchema=marc21nor&maximumRecords=10")
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            # Parse alle treff
            
            root2 = ET.fromstring(r.text)
            SRW = "http://www.loc.gov/zing/srw/"
            records = root2.findall(f"{{{SRW}}}records/{{{SRW}}}record")
            if not records:
                self.status_var.set(f"Ingen treff på '{tittel}'")
                return
            # Vis valgdialog
            self._vis_sokdialog(records, tittel)
        except Exception as e:
            self.status_var.set(f"Søkfeil: {e}")
        finally:
            self.spinner_var.set("")

    def _vis_sokdialog(self, records, tittel):
        """Vis dialog med søketreff."""
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Treff for '{tittel}'")
        dialog.geometry("500x400")
        dialog.grab_set()

        ctk.CTkLabel(dialog, text=f"Vel bok:",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(padx=16, pady=(12, 4))

        scroll = ctk.CTkScrollableFrame(dialog)
        scroll.pack(fill="both", expand=True, padx=16, pady=8)
        scroll.grid_columnconfigure(0, weight=1)

        MNS = "info:lc/xmlns/marcxchange-v1"
        for i, rec_el in enumerate(records):
            rec = rec_el.find(f".//{{{MNS}}}record")
            if rec is None:
                continue
            # Hent tittel og forfattar
            tittel_felt = ""
            forfatter_felt = ""
            for df in rec.findall(f"{{{MNS}}}datafield[@tag='245']"):
                sf = df.find(f"{{{MNS}}}subfield[@code='a']")
                if sf is not None and sf.text:
                    tittel_felt = sf.text.strip().rstrip(" /")
            for df in rec.findall(f"{{{MNS}}}datafield[@tag='100']"):
                sf = df.find(f"{{{MNS}}}subfield[@code='a']")
                if sf is not None and sf.text:
                    forfatter_felt = sf.text.strip().rstrip(",")

            tekst = f"{tittel_felt}"
            if forfatter_felt:
                tekst += f"  –  {forfatter_felt}"

            def vel_bok(r=rec_el, d=dialog):
                # Parse og legg til boka
                try:
                    MNS2 = "info:lc/xmlns/marcxchange-v1"
                    SRW2 = "http://www.loc.gov/zing/srw/"
                    # Wrap i ein fake response
                    xml_str = ET.tostring(r, encoding="unicode")
                    # Bruk parse_mods via wrapper
                    wrapper = f'<searchRetrieveResponse xmlns="{SRW2}"><records><record><recordSchema/><recordPacking/><recordData>{xml_str}</recordData></record></records></searchRetrieveResponse>'
                    bok = parse_mods(wrapper)
                    if bok:
                        bok["kjelde"] = "aja"
                        self.books.append(bok)
                        self._refresh_list()
                        idx = len(self.books) - 1
                        self.book_list.selection_set(idx) if hasattr(self.book_list, 'selection_set') else None
                        self._load_book(idx)
                        self.status_var.set(f"Lagt til: {bok.get('tittel', '')}")
                except Exception as e:
                    self.status_var.set(f"Feil: {e}")
                finally:
                    d.destroy()

            ctk.CTkButton(scroll, text=tekst, anchor="w",
                          fg_color="#2d3748", hover_color="#2b6cb0",
                          corner_radius=6, height=36,
                          font=ctk.CTkFont(size=11),
                          command=vel_bok).grid(row=i, column=0, sticky="ew", pady=2)

        ctk.CTkButton(dialog, text="Avbryt", fg_color="#6b7280",
                      command=dialog.destroy).pack(pady=(0, 12))

    def _serieliste(self):
        """Opnar vindauge for å laga serieliste-etikett."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Serieliste-etikett")
        dialog.geometry("480x200")
        dialog.grab_set()
        dialog.resizable(False, False)

        ctk.CTkLabel(dialog, text="Skriv inn ISBN til ei bok i serien:",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(padx=20, pady=(20, 8))

        isbn_var = ctk.StringVar()
        entry = ctk.CTkEntry(dialog, textvariable=isbn_var, width=300,
                             height=36, corner_radius=8,
                             placeholder_text="ISBN...")
        entry.pack(padx=20, pady=(0, 12))
        entry.focus()

        status = ctk.CTkLabel(dialog, text="", font=ctk.CTkFont(size=11),
                              text_color="gray")
        status.pack()

        def sok():
            isbn = re.sub(r"[\s-]", "", isbn_var.get().strip()).replace("-", "")
            if not isbn:
                return
            status.configure(text="Hentar data...", text_color="gray")
            dialog.update()
            try:
                bok = aja_oppslag(isbn)
                if not bok:
                    status.configure(text="Ikkje funne i Ája.", text_color="#e53e3e")
                    return
                serie = bok.get("serie", "")
                if not serie:
                    status.configure(text="Boka er ikkje del av ein serie.", text_color="#e53e3e")
                    return
                forfatter = bok.get("forfatter", "")
                status.configure(text=f"Hentar serie: {serie}...", text_color="gray")
                dialog.update()
                # Søk på forfattar og filtrer på serie
                bøker = _hent_serie(forfatter, serie, isbn)
                if not bøker:
                    status.configure(text="Ingen treff.", text_color="#e53e3e")
                    return
                dialog.destroy()
                self._vis_serieliste_dialog(serie, bøker, isbn)
            except Exception as e:
                status.configure(text=f"Feil: {e}", text_color="#e53e3e")

        entry.bind("<Return>", lambda e: sok())
        ctk.CTkButton(dialog, text="Hent serie", width=200, height=36,
                      corner_radius=8, fg_color="#6d28d9", hover_color="#5b21b6",
                      command=sok).pack(pady=(0, 20))

    def _vis_serieliste_dialog(self, serie: str, bøker: list, aktiv_isbn: str):
        """Viser serieliste med redigerbare felt, gruppert i etiketter på 5."""
        # Del i grupper på 5
        grupper = [bøker[i:i+5] for i in range(0, len(bøker), 5)]

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Serie: {serie}")
        dialog.geometry("520x600")
        dialog.grab_set()

        ctk.CTkLabel(dialog, text=f"Serie: {serie}",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(padx=16, pady=(16, 2))
        ctk.CTkLabel(dialog,
                     text=f"{len(bøker)} bøker – {len(grupper)} etikett(ar)  |  Blå = vald bok",
                     font=ctk.CTkFont(size=11), text_color="gray").pack()

        scroll = ctk.CTkScrollableFrame(dialog)
        scroll.pack(fill="both", expand=True, padx=16, pady=8)
        scroll.grid_columnconfigure(1, weight=1)

        # Samle alle StringVar-ar og radioknapp-val
        # aktiv_radio_var = global IntVar som held (g_idx * 5 + l_idx) for vald linje
        aktiv_radio_var = ctk.IntVar(value=-1)

        # Set default til ISBN-match
        default_radio = -1
        for g_idx, gruppe in enumerate(grupper):
            for b_idx, b in enumerate(gruppe):
                if b.get("isbn", "") == aktiv_isbn:
                    default_radio = g_idx * 5 + b_idx
        aktiv_radio_var.set(default_radio)

        alle_vars = []
        row = 0
        for g_idx, gruppe in enumerate(grupper):
            if len(grupper) > 1:
                ctk.CTkLabel(scroll, text=f"Etikett {g_idx+1}:",
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color="#4f8ef7").grid(
                                 row=row, column=0, columnspan=3,
                                 sticky="w", pady=(8, 2))
                row += 1
            gruppe_vars = []
            for l_idx in range(5):
                if l_idx < len(gruppe):
                    b = gruppe[l_idx]
                    nr = b.get("nummer", "")
                    tittel = b.get("tittel", "")
                    tekst = f"{nr}. {tittel}" if nr else tittel
                else:
                    tekst = ""

                radio_val = g_idx * 5 + l_idx
                radio = ctk.CTkRadioButton(scroll, text="", variable=aktiv_radio_var,
                                           value=radio_val, width=24, height=28)
                radio.grid(row=row, column=0, padx=(0, 2), pady=1)

                var = ctk.StringVar(value=tekst)
                entry = ctk.CTkEntry(scroll, textvariable=var, height=28,
                                     corner_radius=6,
                                     font=ctk.CTkFont(size=11),
                                     text_color="#e2e8f0")
                entry.grid(row=row, column=1, sticky="ew", pady=1)
                gruppe_vars.append(var)
                row += 1
            alle_vars.append(gruppe_vars)

        def skriv_ut_alle():
            vald = aktiv_radio_var.get()
            for g_idx, gruppe_vars in enumerate(alle_vars):
                linjer = [v.get().strip() for v in gruppe_vars]
                # Fjern tomme linjer frå slutten, men behald hol i midten
                while linjer and not linjer[-1]:
                    linjer.pop()
                if not linjer:
                    continue
                aktiv_idx = (vald - g_idx * 5) if 0 <= (vald - g_idx * 5) < len(linjer) else -1
                xml = _generer_serieliste_dymo(serie, linjer, aktiv_idx)
                skriv_ut_fn(xml, self.printer_var.get())
            dialog.destroy()
            self.status_var.set(f"Serieliste skrive ut: {serie}")

        ctk.CTkButton(dialog, text="Skriv ut alle etiketter",
                      height=40, corner_radius=8,
                      fg_color="#6d28d9", hover_color="#5b21b6",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=skriv_ut_alle).pack(pady=(4, 4))
        ctk.CTkButton(dialog, text="Avbryt", height=32, corner_radius=8,
                      fg_color="#6b7280", hover_color="#4b5563",
                      command=dialog.destroy).pack(pady=(0, 16))

    def _refresh_list(self):
        for btn in self._list_buttons:
            btn.destroy()
        self._list_buttons = []
        for i, b in enumerate(self.books):
            kat = b.get("kategori", "")
            kjelde_ikon = "! " if b.get("kjelde") == "openlibrary" else ""
            tittel = b.get("tittel") or b.get("isbn", "?")
            farge = "#2d3748" if i != self.current_index else "#2b6cb0"
            btn = ctk.CTkButton(
                self.book_list,
                text=f"{kjelde_ikon}{tittel}",
                anchor="w", fg_color=farge,
                hover_color="#2b6cb0",
                corner_radius=6, height=32,
                font=ctk.CTkFont(size=11),
                command=lambda idx=i: self._select_book(idx)
            )
            btn.grid(row=i, column=0, sticky="ew", pady=2)
            self._list_buttons.append(btn)
        antall = len(self.books)
        self.teller_var.set(f"{antall} bok{'ar' if antall != 1 else ''}" if antall else "")

    def _select_book(self, index: int):
        self._lagre(silent=True)
        self._load_book(index)

    def _load_book(self, index: int):
        self.current_index = index
        if 0 <= index < len(self.books):
            b = self.books[index]
            for key, var in self.vars.items():
                var.set(b.get(key, ""))
            self._oppdater_mal()
            self.vars["shelf"].set(b.get("shelf", ""))
            self._last_forsidebilde(b)
            self._refresh_list()
            kjelde = b.get("kjelde", "aja")
            if kjelde == "openlibrary":
                manglar = []
                if not b.get("dewey"):  manglar.append("Dewey")
                if not b.get("serie"):  manglar.append("Serienavn")
                if manglar:
                    self.status_var.set(
                        f"Open Library - fyll inn manuelt: {', '.join(manglar)}")

    def _last_forsidebilde(self, bok: dict):
        url = bok.get("cover_url", "")
        if not url or not PIL_OK:
            self.cover_ctk_label.configure(image=None, text="")
            self._cover_photo = None
            return
        def fetch():
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    img = Image.open(io.BytesIO(r.content))
                    img.thumbnail((90, 130))
                    ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                           size=(img.width, img.height))
                    self.cover_ctk_label.configure(image=ctk_img, text="")
                    self._cover_photo = ctk_img
            except:
                pass
        threading.Thread(target=fetch, daemon=True).start()

    def _lagre(self, silent=False):
        if 0 <= self.current_index < len(self.books):
            for key, var in self.vars.items():
                self.books[self.current_index][key] = var.get()
            kat = self.vars["kategori"].get().lower()
            self.books[self.current_index]["er_biletbok"] = (kat == "biletbøker")
            if not silent:
                self.status_var.set("Endringar lagra.")

    def _fjern(self):
        if self.current_index < 0 or not self.books:
            return
        self.books.pop(self.current_index)
        self.current_index = min(self.current_index, len(self.books) - 1)
        self._refresh_list()
        if self.books:
            self._load_book(self.current_index)
        else:
            self.current_index = -1
            for var in self.vars.values():
                var.set("")
            self.mal_var.set("")
            self.kat_badge.configure(text="")

    def _oppdater_mal(self):
        kat = self.vars.get("kategori", ctk.StringVar()).get()
        if kat.lower() == "biletbøker":
            self.mal_var.set("  Biletbok-mal")
            self.mal_label.configure(fg_color="#c05621")
        else:
            self.mal_var.set("  Standard mal")
            self.mal_label.configure(fg_color="#38a169")
        farge = kat_farge(kat.lower())
        self.kat_badge.configure(text=kat if kat else "", fg_color=farge)

    def _skriv_ut_ein(self):
        self._lagre(silent=True)
        if self.current_index < 0 or not self.books:
            return
        bok = self.books[self.current_index]
        xml = generer_dymo(bok)
        if skriv_ut(xml, self.printer_var.get()):
            self.status_var.set(f"Sendt til skrivar: {bok.get('tittel', '')}")

    def _skriv_ut_alle(self):
        self._lagre(silent=True)
        if not self.books:
            messagebox.showinfo("Ingen bøker", "Ingen bøker å skriva ut.")
            return
        if not messagebox.askyesno("Skriv ut alle",
                                   f"Vil du skriva ut {len(self.books)} etikett(ar)?"):
            return
        feil = 0
        for i, bok in enumerate(self.books):
            self.status_var.set(f"Skriv ut {i+1}/{len(self.books)}: {bok.get('tittel','')}")
            self.update()
            xml = generer_dymo(bok)
            if not skriv_ut(xml, self.printer_var.get()):
                feil += 1
        if feil == 0:
            self.status_var.set(f"Alle {len(self.books)} etiketter skrivne ut!")
        else:
            self.status_var.set(f"Ferdig - {feil} etikett(ar) feila.")

    def _lagre_skriver(self):
        self.settings["printer"] = self.printer_var.get()
        save_settings(self.settings)
        self.status_var.set("Skrivarinnstilling lagra.")

if __name__ == "__main__":
    app = App()
    app.mainloop()
