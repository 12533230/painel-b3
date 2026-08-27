#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera a versão PÚBLICA do painel (sem identidade Insignia) a partir do build
normal: out/Painel_B3.html -> out/public_index.html (publicada em docs/p/).
Troca título, favicon, logo, rodapés e aplica paleta neutra por cima.
Aborta se sobrar qualquer menção à marca.
"""
import re, sys
from pathlib import Path

BASE = Path(__file__).parent
SRC = BASE / "out" / "Painel_B3.html"
OUT = BASE / "out" / "public_index.html"

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
           "viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E"
           "%F0%9F%93%8A%3C/text%3E%3C/svg%3E")

PALETA = """<style>
/* Versão pública — paleta neutra (sobrepõe a folha principal) */
:root{
  --page:#f6f8fa; --surface:#ffffff; --ink:#0f172a; --ink2:#1e3a5f; --muted:#64748b;
  --grid:#e2e8f0; --axis:#94a3b8; --border:rgba(15,23,42,.13);
  --s1:#2563eb; --s2:#d97706; --s3:#7c3aed;
  --good:#15803d; --bad:#b91c1c; --wash:rgba(100,116,139,.10);
  --link:#1d4ed8; --brandbar:#0f172a; --brandink:#f8fafc;
}
:root[data-theme="dark"]{
  --page:#0b1220; --surface:#101b30; --ink:#f1f5f9; --ink2:#c7d2e2; --muted:#8ea3bd;
  --grid:#1f2e48; --axis:#31456a; --border:rgba(241,245,249,.14);
  --s1:#60a5fa; --s2:#f59e0b; --s3:#a78bfa;
  --good:#4ade80; --bad:#f87171; --wash:rgba(148,163,184,.12);
  --link:#93c5fd; --brandbar:#0b1220; --brandink:#f8fafc;
}
.ticker{border-bottom-color:#475569}
.tk .up{color:#86efac}.tk .dn{color:#fca5a5}
.search input:focus{border-color:#93c5fd}
.top .btn:hover{border-color:#93c5fd}
.btn:hover{border-color:#64748b;color:var(--ink)}
.links a:hover{border-color:#64748b}
.agsuper{background:rgba(217,119,6,.18)}
</style>"""

def main():
    html = SRC.read_text(encoding="utf-8")
    html = html.replace("<title>Insignia Partners · Painel B3</title>",
                        "<title>Painel B3 · Mercados ao vivo</title>")
    html = re.sub(r'<link rel="icon"[^>]*>',
                  '<link rel="icon" type="image/svg+xml" href="' + FAVICON + '">', html, count=1)
    html = re.sub(r'<img class="logo"[^>]*>',
                  '<span style="font-size:18px" aria-hidden="true">\U0001F4CA</span>', html, count=1)
    html = html.replace("Insignia Partners · painel interno.",
                        "Painel de mercado — projeto independente, sem fins comerciais.")
    html = html.replace("painel interno da Insignia Partners, informativo e educacional",
                        "painel informativo e educacional, independente")
    html = html.replace("não são curadoria da Insignia nem recomendação",
                        "não são curadoria nem recomendação")
    html = html.replace("Identidade visual Insignia Partners — paleta do Manual de Marca + tema PPT v4",
                        "Paleta base (a versão pública sobrepõe com paleta neutra no fim do head)")
    html = html.replace("</head>", PALETA + "\n</head>", 1)
    if "Insignia" in html:
        print("[public] ERRO: ainda há menção à marca no HTML público", file=sys.stderr)
        sys.exit(1)
    OUT.write_text(html, encoding="utf-8")
    print(f"[public] OK {OUT} ({OUT.stat().st_size/1024:.0f} KB)", file=sys.stderr)

if __name__ == "__main__":
    main()
