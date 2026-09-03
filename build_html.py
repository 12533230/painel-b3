#!/usr/bin/env python3
"""Injeta out/painel_data.json no template e gera out/Painel_B3.html"""
import datetime as _dt
from pathlib import Path
BASE = Path(__file__).parent
tpl = (BASE / "painel_template.html").read_text(encoding="utf-8")
data = (BASE / "out" / "painel_data.json").read_text(encoding="utf-8")
data = data.replace("</", "<\\/")  # não quebrar o <script>
html = tpl.replace("__DATA__", data)
macro = (BASE / "out" / "macro_snapshot.json")
macro = macro.read_text(encoding="utf-8") if macro.exists() else "{}"
html = html.replace("__MACRO__", macro.replace("</", "<\\/"))
quotes = (BASE / "data" / "quotes.json")
quotes = quotes.read_text(encoding="utf-8") if quotes.exists() else "{}"
html = html.replace("__QUOTES__", quotes.replace("</", "<\\/"))
wl = (BASE / "data" / "watchlists.json")
wl = wl.read_text(encoding="utf-8") if wl.exists() else "{}"
html = html.replace("__WATCHLISTS__", wl.replace("</", "<\\/"))
html = html.replace("__BUILDAT__", _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
# marca Insignia (base64 gerados a partir de brand/)
logo = (BASE / "brand" / "logo_header.b64")
fav = (BASE / "brand" / "favicon.b64")
if logo.exists():
    html = html.replace("__LOGO__", logo.read_text().strip())
if fav.exists():
    html = html.replace("__FAVICON__", fav.read_text().strip())
# logo empilhado (branco + alpha) usado na tela de carregamento
import base64 as _b64
boot = (BASE / "brand" / "logo_full.png")
if boot.exists():
    html = html.replace("__LOGOBOOT__", _b64.b64encode(boot.read_bytes()).decode())
elif logo.exists():
    html = html.replace("__LOGOBOOT__", logo.read_text().strip())
out = BASE / "out" / "Painel_B3.html"
out.write_text(html, encoding="utf-8")
print(f"OK {out} ({out.stat().st_size/1024:.0f} KB)")
