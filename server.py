"""
Boketikett-generator – nettlesarversjon
=======================================
Startar ein liten nettstad på denne PC-en (http://localhost:8765) som
viser etikettprogrammet i nettlesaren. Oppslag i Ája og utskrift skjer
her i Python, så nettlesaren treng ikkje snakke med Ája eller Dymo sjølv.

Start:  python server.py              (opnar nettlesaren automatisk)
        python server.py --ikkje-opne (t.d. ved autostart)
"""

import json, socket, sys, threading, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import kjerne

PORT = 8765
ADRESSE = f"http://localhost:{PORT}/"
WEB_DIR = Path(__file__).parent / "web"
TILLATNE_VERTAR = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}
FILTYPAR = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}


def _skrivar(data: dict) -> str:
    return (data.get("skrivar") or kjerne.load_settings().get("printer")
            or "DYMO LabelWriter 450 TwinTurbo")


def api_get(sti: str, q: dict):
    if sti == "/api/konfig":
        return {
            "kategoriar": kjerne.ALLE_KATEGORIAR,
            "malformer": kjerne.MALFOMER,
            "fargar": kjerne.KAT_FARGAR,
            "skrivar": _skrivar({}),
        }
    if sti == "/api/isbn":
        isbn = "".join(c for c in q.get("isbn", "") if c.isdigit() or c in "xX")
        bok = kjerne.aja_oppslag(isbn)
        if bok:
            bok["isbn"] = isbn
        return {"bok": bok}
    if sti == "/api/sok":
        return {"bøker": kjerne.sok_tittel(q.get("tittel", "").strip())}
    if sti == "/api/serie":
        isbn = "".join(c for c in q.get("isbn", "") if c.isdigit() or c in "xX")
        bok = kjerne.aja_oppslag(isbn)
        if not bok:
            return {"feil": "Fann ikkje boka i Ája."}
        if not bok.get("serie"):
            return {"feil": "Boka er ikkje del av ein serie."}
        bøker = kjerne.hent_serie(bok.get("forfatter", ""), bok["serie"], isbn)
        if not bøker:
            return {"feil": "Fann ingen andre bøker i serien."}
        return {"serie": bok["serie"], "isbn": isbn, "bøker": bøker}
    return None


def api_post(sti: str, data: dict):
    if sti == "/api/forhandsvis":
        return {"xml": kjerne.generer_dymo(data.get("bok", {}))}
    if sti == "/api/skriv-ut":
        ok, melding = kjerne.skriv_ut(kjerne.generer_dymo(data.get("bok", {})), _skrivar(data))
        return {"ok": ok, "melding": melding}
    if sti == "/api/serieliste/forhandsvis":
        return {"xml": kjerne.generer_serieliste_dymo(
            data.get("serie", ""), data.get("linjer", []), int(data.get("aktiv", -1)))}
    if sti == "/api/serieliste/skriv-ut":
        xml = kjerne.generer_serieliste_dymo(
            data.get("serie", ""), data.get("linjer", []), int(data.get("aktiv", -1)))
        ok, melding = kjerne.skriv_ut(xml, _skrivar(data))
        return {"ok": ok, "melding": melding}
    if sti == "/api/skrivar":
        innst = kjerne.load_settings()
        innst["printer"] = str(data.get("skrivar", "")).strip()
        kjerne.save_settings(innst)
        return {"ok": True}
    return None


class Handsamar(BaseHTTPRequestHandler):
    server_version = "Boketikett/1.0"

    def log_message(self, fmt, *args):
        pass  # hald konsollvindauget roleg

    def _send(self, kode: int, innhald: bytes, typ: str):
        self.send_response(kode)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(innhald)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(innhald)

    def _json(self, data, kode: int = 200):
        self._send(kode, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _godkjend_vert(self) -> bool:
        # Berre svar på førespurnader til localhost, ikkje frå andre nettstader
        # som prøver å nå programmet via ei eiga domeneadresse.
        if self.headers.get("Host", "") in TILLATNE_VERTAR:
            return True
        self._json({"feil": "Ugyldig vert"}, 403)
        return False

    def do_GET(self):
        if not self._godkjend_vert():
            return
        url = urlparse(self.path)
        if url.path.startswith("/api/"):
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                svar = api_get(url.path, q)
            except Exception as e:
                return self._json({"feil": str(e)}, 500)
            return self._json(svar) if svar is not None else self._json({"feil": "Ukjend adresse"}, 404)

        namn = "index.html" if url.path in ("", "/") else url.path.lstrip("/")
        fil = (WEB_DIR / namn).resolve()
        if WEB_DIR.resolve() not in fil.parents or not fil.is_file():
            return self._send(404, b"Ikkje funne", "text/plain; charset=utf-8")
        self._send(200, fil.read_bytes(), FILTYPAR.get(fil.suffix, "application/octet-stream"))

    def do_POST(self):
        if not self._godkjend_vert():
            return
        # Krev JSON. Andre nettstader kan ikkje sende JSON hit utan løyve
        # frå nettlesaren, så ingen kan skrive ut via ei lenkje eller eit skjema.
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json({"feil": "Forventa JSON"}, 415)
        try:
            lengd = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(lengd) or b"{}")
            svar = api_post(urlparse(self.path).path, data)
        except Exception as e:
            return self._json({"feil": str(e)}, 500)
        return self._json(svar) if svar is not None else self._json({"feil": "Ukjend adresse"}, 404)


def kjorer_alt() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def main():
    opne = "--ikkje-opne" not in sys.argv
    if kjorer_alt():
        print(f"Etikettprogrammet køyrer alt på {ADRESSE}")
        if opne:
            webbrowser.open(ADRESSE)
        return
    tenar = ThreadingHTTPServer(("127.0.0.1", PORT), Handsamar)
    print(f"Etikettprogrammet køyrer på {ADRESSE}")
    print("Lat dette vindauget stå ope (det kan minimerast). Lukk det for å stoppe programmet.")
    if opne:
        threading.Timer(0.8, webbrowser.open, args=(ADRESSE,)).start()
    try:
        tenar.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
