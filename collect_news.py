#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coletor de notícias por empresa (roda 1x/dia no update.yml).
Para cada empresa listada (data/b3_companies.json), busca as manchetes mais
recentes no RSS do Google News (query: nome + B3) e grava data/news.json:

  {"updatedAt": iso, "n": {codigoCVM: [{"t": título, "src": veículo,
                                        "d": "dd/mm", "u": link}, ...]}}

Tolerante a falha: empresa que falhar mantém as notícias do arquivo anterior.
"""
import datetime as dt
import json, re, sys, time
from pathlib import Path
import requests
from lxml import etree

BASE = Path(__file__).parent
DATA = BASE / "data"
OUT_FILE = DATA / "news.json"
UA = {"User-Agent": "Mozilla/5.0 (painel-b3; uso educacional/interno; contato via repo)"}
RSS = "https://news.google.com/rss/search"
MAX_POR_EMPRESA = 6

def log(*a): print("[news]", *a, file=sys.stderr)

def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default

def parse_dt(s):
    # "Tue, 25 Aug 2026 14:03:00 GMT" -> "25/08"
    m = re.match(r"\w+, (\d{2}) (\w{3}) (\d{4})", s or "")
    if not m:
        return ""
    meses = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
             "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
    return f"{m.group(1)}/{meses.get(m.group(2), '01')}"

EXCL_MKT = {"BALCAO NAO ORG.", "OUTROS", "SOMA"}
EXCL_SECTORS = {"Carga Inicial", "Setor Inicial"}

def fetch_news(session, nome):
    """Lista de notícias (possivelmente vazia) no sucesso; None só em falha real."""
    try:
        r = session.get(RSS, params={"q": f'"{nome}" B3', "hl": "pt-BR", "gl": "BR",
                                     "ceid": "BR:pt-419"}, timeout=(5, 10))
        r.raise_for_status()
        root = etree.fromstring(r.content)
        out = []
        for it in root.iter("item"):
            t = (it.findtext("title") or "").strip()
            u = (it.findtext("link") or "").strip()
            src = (it.findtext("source") or "").strip()
            # Google News costuma anexar " - Veículo" ao título
            t = re.sub(r" - [^-]+$", "", t)[:140]
            d = parse_dt(it.findtext("pubDate"))
            if t and u:
                out.append({"t": t, "src": src[:40], "d": d, "u": u})
            if len(out) >= MAX_POR_EMPRESA:
                break
        return out  # [] = feed válido sem manchetes (não é falha)
    except Exception:
        return None

def main():
    b3 = load_json(DATA / "b3_companies.json", {})
    empresas = []
    for c in b3.get("companies") or []:
        # mesmo universo do process.py (mkt é o SEGMENTO de listagem: Novo Mercado, Nível 1…)
        parts = [p.strip() for p in (c.get("ind") or "").split("/")]
        if len(parts) != 3 or parts[0] in EXCL_SECTORS or (c.get("mkt") or "").strip() in EXCL_MKT:
            continue
        try:
            cvm = str(int(c["codeCVM"]))
        except Exception:
            continue
        nome = (c.get("trad") or c.get("name") or "").strip()
        if nome:
            empresas.append((cvm, nome))
    prev = load_json(OUT_FILE, {})
    n = dict(prev.get("n") or {})
    s = requests.Session(); s.headers.update(UA)
    ok = 0
    vazios_seguidos = 0
    for i, (cvm, nome) in enumerate(empresas):
        itens = fetch_news(s, nome)
        if itens is None:  # falha real (HTTP/parse) — feed vazio NÃO conta
            vazios_seguidos += 1
            if vazios_seguidos >= 30:  # bloqueio/limite geral: preserva o publicado
                log("30 falhas de rede em sequência — abortando a coleta")
                break
        else:
            vazios_seguidos = 0
            if itens:  # feed vazio mantém as notícias antigas da empresa
                n[cvm] = itens
                ok += 1
        if i % 100 == 0:
            log(f"{i}/{len(empresas)} ({ok} ok)")
        time.sleep(0.35)  # educado com o Google News
    log(f"{ok} empresas com notícias de {len(empresas)} ({len(n)} no arquivo)")
    if ok == 0:
        log("nada coletado — abortando sem gravar")
        sys.exit(1)
    snap = {"updatedAt": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "n": n}
    OUT_FILE.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"OK {OUT_FILE} ({OUT_FILE.stat().st_size/1024:.0f} KB)")

if __name__ == "__main__":
    main()
