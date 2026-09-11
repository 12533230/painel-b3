#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Índices da B3 por papel — "esta ação está no Ibovespa? no IDIV? no Small Cap?".

Fonte: `indexProxy/indexCall/GetStockIndex` com {"language":"pt-br"}. Medido em
10/09/2026: **uma única requisição de 47 KB** devolve 469 tickers, cada um com a
lista dos índices que compõe (40 índices distintos). O conjunto IBOV extraído
dela é IDÊNTICO ao do `GetPortfolioDay` (76 papéis, zero diferença) — então não
vale fazer 40 chamadas para obter o mesmo.

O peso de cada papel NÃO vem nesse endpoint. Para os índices que o painel exibe
com peso, complementamos com `GetPortfolioDay` (traz `part` = peso % e
`theoricalQty`). Aqui pegamos só os índices amplos e setoriais mais usados.

O que NÃO existe nessas APIs: composição histórica. Passar {"date":"2026-06-30"}
é **ignorado** — o header continua com a data de hoje. Portanto o painel só pode
dizer "carteira de <data de hoje>", nunca "como era o IBOV em 2020". Prometer
isso seria número errado na tela.

Saída: data/indices.json
  {"updatedAt", "vigencia": {...header...}, "porTicker": {"PETR4": ["IBOV","IBRA",…]},
   "indices": {"IBOV": {"nome", "n", "pesos": {"PETR4": 4.83, …}, "data": "10/09/26"}}}
"""
import base64
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).parent
DATA = BASE / "data"
OUT_FILE = DATA / "indices.json"
DATA.mkdir(exist_ok=True)

API = "https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall"
UA = {"User-Agent": "Mozilla/5.0 (painel-b3; uso educacional/interno; contato via repo)"}
S = requests.Session()
S.headers.update(UA)

# Índices em que o peso agrega valor no painel (amplos + setoriais que o consultor usa).
# A sigla do Small Cap é SMLL — "SMAL" devolve vazio (SMAL11 é o ETF, não o índice).
COM_PESO = [
    ("IBOV", "Ibovespa"),
    ("IBXX", "IBrX 100"),
    ("IBRA", "IBrA — Brasil Amplo"),
    ("SMLL", "Small Caps"),
    ("MLCX", "MidLarge Cap"),
    ("IDIV", "Dividendos"),
    ("IFNC", "Financeiro"),
    ("IMOB", "Imobiliário"),
    ("UTIL", "Utilidade pública"),
    ("ICON", "Consumo"),
    ("IEEX", "Energia elétrica"),
    ("INDX", "Industrial"),
    ("IMAT", "Materiais básicos"),
    ("IGCX", "Governança corporativa"),
    ("ISEE", "Sustentabilidade"),
]
# Nomes legíveis dos demais índices do mapa reverso. Medido em 10/09/2026: a resposta
# traz 40 siglas, e a API NÃO devolve o nome de nenhuma delas. Só entram aqui as que
# eu confirmo; as outras aparecem na tela pela própria sigla, porque inventar o nome de
# um índice é publicar informação que não foi verificada. As siglas hoje sem nome são
# AGFS, BNCO, IBBC, IBBE, IBBR, IBEE, IBEP, IBEW, IBHB, IBLV, IBSD, IBST, IFES, IGNM
# e SCSR — para nomeá-las, confirmar na página de índices da B3 antes.
NOMES = {
    "BDRX": "BDRs não patrocinados",
    "GPTW": "Great Place to Work",
    "ICO2": "Carbono eficiente",
    "IDVR": "Dividendos com reinvestimento",
    "IFIL": "FIIs de alta liquidez",
    "IFIX": "Fundos imobiliários",
    "IGCT": "Governança corporativa trade",
    "IVBX": "IVBX-2",
    "ITAG": "Ações com tag along diferenciado",
    "IBXL": "IBrX 50",
}


def log(*a):
    print("[indices]", *a, file=sys.stderr)


def b64(o):
    return base64.b64encode(json.dumps(o).encode()).decode()


def chama(rota, params, tentativas=3):
    url = f"{API}/{rota}/{b64(params)}"
    for i in range(1, tentativas + 1):
        try:
            r = S.get(url, timeout=45)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log(f"{rota} {params.get('index', '')} tentativa {i}/{tentativas}: {e!r}")
            if i < tentativas:
                time.sleep(4 * i)
    return None


def main():
    # ---- 1. mapa reverso: 1 requisição para todos os papéis
    d = chama("GetStockIndex", {"language": "pt-br"})
    if not d or not (d.get("results")):
        log("GetStockIndex não respondeu — abortando sem gravar")
        sys.exit(1)
    header = d.get("header") or {}
    por_ticker = {}
    for x in d["results"]:
        cod = (x.get("code") or "").strip().upper()
        idxs = [i.strip().upper() for i in (x.get("indexes") or "").split(",") if i.strip()]
        if cod and idxs:
            por_ticker[cod] = sorted(set(idxs))
    todos = sorted({i for v in por_ticker.values() for i in v})
    log(f"GetStockIndex: {len(por_ticker)} tickers · {len(todos)} índices · "
        f"vigência {header.get('startMonth')}-{header.get('endMonth')}/{header.get('year')}")
    if len(por_ticker) < 200:
        log(f"apenas {len(por_ticker)} tickers — resposta pequena demais, abortando")
        sys.exit(1)

    # ---- 2. peso, só nos índices que o painel exibe
    indices = {}
    for sigla, nome in COM_PESO:
        # o pageSize de 200 funciona neste endpoint (ao contrário do de proventos,
        # que devolve 200 com corpo vazio acima de 100)
        r = chama("GetPortfolioDay", {"language": "pt-br", "pageNumber": 1,
                                      "pageSize": 200, "index": sigla, "segment": "1"})
        res = (r or {}).get("results") or []
        if not res:
            # não é motivo para abortar: o mapa reverso já cobre o selo "está no IBOV"
            log(f"{sigla}: sem carteira nesta execução (fica só no mapa reverso)")
            indices[sigla] = {"nome": nome, "n": sum(1 for v in por_ticker.values() if sigla in v)}
            continue
        h = (r.get("header") or {})
        pesos = {}
        for x in res:
            cod = (x.get("cod") or "").strip().upper()
            try:
                pesos[cod] = round(float(str(x.get("part")).replace(",", ".")), 3)
            except Exception:
                pass
        indices[sigla] = {"nome": nome, "n": len(res), "data": h.get("date"),
                          "pesos": pesos,
                          "reductor": h.get("reductor"), "qtdTeorica": h.get("theoricalQty")}
        log(f"{sigla}: {len(res)} papéis, {len(pesos)} com peso ({h.get('date')})")
        time.sleep(0.6)   # educado com o endpoint

    # índices sem peso: registra só o nome e a contagem vinda do mapa reverso
    for sigla in todos:
        if sigla in indices:
            continue
        indices[sigla] = {"nome": NOMES.get(sigla, sigla),
                          "n": sum(1 for v in por_ticker.values() if sigla in v)}

    snap = {
        "updatedAt": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fonte": "B3 — indexProxy/indexCall (GetStockIndex e GetPortfolioDay)",
        "vigencia": {"atualizadoEm": header.get("update"),
                     "mesInicio": header.get("startMonth"),
                     "mesFim": header.get("endMonth"),
                     "ano": header.get("year")},
        "nota": ("Composição do dia da coleta. A API da B3 não fornece carteira "
                 "histórica: pedir uma data anterior é ignorado, então o painel não "
                 "publica 'como era a carteira em outra data'."),
        "porTicker": por_ticker,
        "indices": indices,
    }
    OUT_FILE.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    log(f"OK {OUT_FILE} ({OUT_FILE.stat().st_size/1024:.0f} KB)")
    # prova no log: o IBOV do mapa reverso bate com a carteira?
    a = {t for t, v in por_ticker.items() if "IBOV" in v}
    b = set((indices.get("IBOV") or {}).get("pesos") or {})
    if b:
        log(f"conferência IBOV: mapa reverso {len(a)} × carteira {len(b)} · "
            f"só no mapa: {sorted(a - b)} · só na carteira: {sorted(b - a)}")


if __name__ == "__main__":
    main()
