#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Manchetes gerais (Brasil & Macro) coletadas fora do build diário.

Antes elas só existiam dentro do macro_snapshot.json, que o build_html.py embute
no HTML: manchete só mudava quando o painel inteiro era regerado — 1x por dia em
dia útil, e nem isso quando a CVM ou o Fundamentus falhavam e o build abortava.
Aqui as mesmas funções do collect.py rodam sozinhas, a cada 2 horas, todos os
dias, e gravam data/news_macro.json. A página lê esse arquivo em runtime e usa o
embutido só como reserva.

Reaproveita collect.py de propósito: manchete tem de vir da MESMA função que o
build usa, senão as duas versões divergem sem ninguém perceber.
"""
import datetime as dt
import json, sys
from pathlib import Path

import collect   # define reddit_news(), veiculos(), gnews() e o fallback PREV

BASE = Path(__file__).parent
OUT_FILE = BASE / "data" / "news_macro.json"

def log(*a): print("[news-macro]", *a, file=sys.stderr)

def main():
    manchetes, veiculos, reddit = [], {}, {"news": [], "disc": []}
    try:
        manchetes = collect.gnews() or []
    except Exception as e:
        log("Google News falhou:", repr(e))
    try:
        veiculos = collect.veiculos() or {}
    except Exception as e:
        log("RSS dos veículos falhou:", repr(e))
    try:
        reddit = collect.reddit_news() or {"news": [], "disc": []}
    except Exception as e:
        log("Reddit falhou:", repr(e))

    n_veic = sum(len(v.get("itens") or []) for lista in veiculos.values() for v in lista)
    log(f"manchetes={len(manchetes)} itens de veículos={n_veic} "
        f"reddit={len(reddit.get('news') or [])}+{len(reddit.get('disc') or [])}")
    # nada de novo em nenhuma das três fontes: não sobrescreve o arquivo publicado
    if not manchetes and not n_veic and not (reddit.get("news") or reddit.get("disc")):
        log("nenhuma fonte respondeu — abortando sem gravar")
        sys.exit(1)

    snap = {"updatedAt": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "manchetes": manchetes, "veiculos": veiculos, "reddit": reddit}
    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"OK {OUT_FILE} ({OUT_FILE.stat().st_size/1024:.0f} KB)")

if __name__ == "__main__":
    main()
