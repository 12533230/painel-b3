#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coletor de candles diários (roda 1x/dia no workflow update.yml).
Para cada símbolo do painel (B3 completa + watchlists + índices, o mesmo
universo do collect_quotes), baixa ~3 meses de OHLC diário no endpoint
público de gráficos do Yahoo Finance e grava data/candles.json.

O candle do dia corrente é completado AO VIVO no navegador (B3/relay),
então este arquivo só precisa do histórico até o último fechamento.

Formato (compacto):
  {"updatedAt": iso, "c": {SIMBOLO: [[diaEpoch, o, h, l, c], ...]}}
  diaEpoch = dias desde 1970 (UTC). Chaves B3 sem sufixo .SA.
Tolerante a falha: símbolo que falhar mantém a série do arquivo anterior.
"""
import datetime as dt
import json, sys, time
from pathlib import Path
import requests

from collect_quotes import all_symbols, load_json

BASE = Path(__file__).parent
DATA = BASE / "data"
OUT_FILE = DATA / "candles.json"
UA = {"User-Agent": "Mozilla/5.0 (painel-b3; uso educacional/interno; contato via repo)"}
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"

def log(*a): print("[candles]", *a, file=sys.stderr)

def fetch_candles(session, ysym):
    """~3 meses de OHLC diário; devolve lista [[dia,o,h,l,c],...] ou None."""
    try:
        r = session.get(CHART.format(sym=ysym),
                        params={"range": "3mo", "interval": "1d"}, timeout=(5, 10))
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        ts = res.get("timestamp") or []
        q = res["indicators"]["quote"][0]
        out = []
        for i, t in enumerate(ts):
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            if None in (o, h, l, c) or c <= 0:
                continue
            out.append([int(t // 86400), round(o, 4), round(h, 4), round(l, 4), round(c, 4)])
        return out or None
    except Exception:
        return None

def main():
    syms = all_symbols()          # yahoo_symbol -> chave do painel
    prev = load_json(OUT_FILE, {})
    c = dict(prev.get("c") or {})  # falha por símbolo mantém a série anterior
    s = requests.Session(); s.headers.update(UA)
    lista = sorted(syms)
    ok = 0
    vazios_seguidos = 0
    for i, ysym in enumerate(lista):
        serie = fetch_candles(s, ysym)
        if serie:
            c[syms[ysym]] = serie
            ok += 1
            vazios_seguidos = 0
        else:
            vazios_seguidos += 1
            if vazios_seguidos >= 25:  # degradação geral do Yahoo: preserva o publicado
                log("25 símbolos falhando em sequência — abortando a coleta")
                break
        if i % 100 == 0:
            log(f"{i}/{len(lista)} ({ok} ok)")
        time.sleep(0.15)
    log(f"{ok} séries novas de {len(lista)} símbolos ({len(c)} no arquivo)")
    if ok == 0:
        log("nada coletado — abortando sem gravar")
        sys.exit(1)
    snap = {"updatedAt": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "c": c}
    OUT_FILE.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"OK {OUT_FILE} ({OUT_FILE.stat().st_size/1024:.0f} KB)")

if __name__ == "__main__":
    main()
