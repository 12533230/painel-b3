#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coletor rápido de cotações (roda no GitHub Actions a cada ~15 min em pregão).
Busca no Yahoo Finance (endpoint público "spark", em lotes) os preços de:
  - todas as ações da B3 (data/b3_companies.json, sufixo .SA)
  - ETFs da B3 e ativos dos EUA (data/watchlists.json)
  - índices (^BVSP, ^GSPC, ^IXIC, ^DJI, ^RUT, ^VIX, ^TNX)
e grava data/quotes.json — que o painel consulta ao vivo via raw.githubusercontent.

Tolerante a falha: mantém o último valor de cada símbolo que falhar.
Saída: {"updatedAt": iso, "q": {SIMBOLO: {"n": nome, "p": preço, "pv": fech. anterior,
        "cur": moeda, "t": epoch do último negócio}}}
Chaves da B3 ficam SEM o sufixo .SA (PETR4, BOVA11…); índices/EUA como no Yahoo.
"""
import datetime as dt
import json, sys, time
from pathlib import Path
import requests

BASE = Path(__file__).parent
DATA = BASE / "data"
OUT_FILE = DATA / "quotes.json"
UA = {"User-Agent": "Mozilla/5.0 (painel-b3; uso educacional/interno; contato via repo)"}
SPARK = "https://query1.finance.yahoo.com/v7/finance/spark"
BATCH = 20

def log(*a): print("[quotes]", *a, file=sys.stderr)

def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default

def all_symbols():
    """Monta a lista completa de símbolos Yahoo e o mapa símbolo->chave do painel."""
    syms = {}  # yahoo_symbol -> painel_key
    comps = load_json(DATA / "b3_companies.json", {}).get("companies", [])
    for c in comps:
        for code in c.get("codes") or []:
            code = code.strip().upper()
            if code:
                syms[code + ".SA"] = code
    wl = load_json(DATA / "watchlists.json", {})
    for cat in (wl.get("etfs_b3") or {}).values():
        for e in cat:
            t = e["t"].strip().upper()
            syms[t + ".SA"] = t
    for key in ("us_indices", "us_etfs", "us_stocks"):
        for e in wl.get(key) or []:
            t = e["t"].strip()
            syms[t] = t
    for idx in ("^BVSP", "^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX", "^TNX"):
        syms.setdefault(idx, idx)
    return syms

def fetch_batch(session, symbols):
    """Um lote no spark; devolve dict yahoo_symbol -> meta. Falha => {}."""
    params = {"symbols": ",".join(symbols), "range": "1d", "interval": "30m"}
    for tent in (1, 2):
        try:
            r = session.get(SPARK, params=params, timeout=(5, 10))
            r.raise_for_status()
            out = {}
            for res in (r.json().get("spark", {}).get("result") or []):
                try:
                    meta = res["response"][0]["meta"]
                    out[meta["symbol"]] = meta
                except Exception:
                    pass
            return out
        except Exception as e:
            log(f"lote falhou (tentativa {tent}):", repr(e))
            time.sleep(3 * tent)
    return {}

def main():
    syms = all_symbols()
    prev = load_json(OUT_FILE, {})
    q = dict(prev.get("q") or {})  # começa do último snapshot: falha mantém valor antigo
    s = requests.Session(); s.headers.update(UA)
    lista = sorted(syms)
    ok = 0
    vazios_seguidos = 0
    for i in range(0, len(lista), BATCH):
        lote = lista[i:i + BATCH]
        metas = fetch_batch(s, lote)
        if not metas:
            vazios_seguidos += 1
            if vazios_seguidos >= 5:  # Yahoo em degradação geral: aborta cedo, preserva o publicado
                log("5 lotes vazios seguidos — abortando a coleta")
                break
        else:
            vazios_seguidos = 0
        for ysym, m in metas.items():
            key = syms.get(ysym) or ysym
            p = m.get("regularMarketPrice")
            pv = m.get("chartPreviousClose") or m.get("previousClose")
            if p is None or float(p) <= 0:  # 0.0 = papel suspenso; não sobrescrever valor bom anterior
                continue
            q[key] = {
                "n": (m.get("shortName") or m.get("longName") or key)[:60],
                "p": round(float(p), 4),
                "pv": round(float(pv), 4) if pv else None,
                "cur": m.get("currency"),
                "t": m.get("regularMarketTime"),
            }
            ok += 1
        time.sleep(0.4)  # educado com o endpoint
    log(f"{ok} cotações novas de {len(lista)} símbolos ({len(q)} no arquivo)")
    if ok == 0:
        # nada coletado: não regravar (recarimbaria dados velhos com updatedAt novo);
        # o run fica vermelho no Actions e o snapshot publicado mantém o carimbo honesto
        log("nada coletado — abortando sem gravar")
        sys.exit(1)
    snap = {"updatedAt": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "q": q}
    OUT_FILE.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"OK {OUT_FILE} ({OUT_FILE.stat().st_size/1024:.0f} KB)")

if __name__ == "__main__":
    main()
