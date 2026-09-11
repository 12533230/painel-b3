#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Histórico longo de preço (10 anos, fechamento mensal) por papel.

É o habilitador de várias telas que hoje não existem: retorno de 1/3/5/10 anos,
múltiplo contra o próprio histórico da empresa (percentil), preço × lucro por
ação, performance relativa ao Ibovespa e volatilidade.

Fonte: `query1.finance.yahoo.com/v8/finance/chart/<TICKER>.SA?range=10y&interval=1mo`.
Medido em 10/09/2026: 16 KB e 121 pontos por papel, ~880 ms cada.

DECISÕES QUE VIRARAM CÓDIGO (todas medidas):

- **User-Agent de navegador é obrigatório.** Com o UA do robô a primeira chamada
  volta HTTP 429. O `collect_quotes.py` usa o endpoint `spark`, que tolera; o
  `chart` não.
- **`close` e `adjclose` NÃO são intercambiáveis.** No PETR4 de 10 anos atrás o
  `close` é 17,69 e o `adjclose` é 4,43 — trocar os dois inverte completamente o
  P/L histórico. Regra: **`adjclose` para RETORNO** (já embute provento e
  desdobramento) e **`close` para múltiplo histórico** (é o preço que o mercado
  via naquele dia, o que casa com o lucro por ação da época).
- **Retorno de preço e retorno total não se comparam.** O `^BVSP` é índice de
  preço, sem dividendo. Comparar o `adjclose` da ação (retorno total) com o
  `^BVSP` infla a ação de graça. Por isso guardamos as duas séries e publicamos
  **dois números rotulados**: "retorno de preço" (close × close) e "retorno
  total" (adjclose, com provento reinvestido). O painel nunca mistura os eixos.
- **O Yahoo não cobre tudo.** Amostra de 32 papéis: 26 OK (81%). Falham
  micro-caps (QVQP3, AVLL11, AESO3, BETP3, CATA3) e papel renomeado — ELET3 dá
  404 porque virou AXIA3. Papel sem série sai do arquivo com o motivo, e a tela
  mostra ausência, não zero.
- **Diário de 5 anos é inviável aqui**: 138 KB por papel, ~60 MB no total. Este
  coletor é só mensal; o diário de 6 meses continua no `collect_candles.py`.

Saída: `data/precos_longo.json`
  {"updatedAt", "meses": [aaaa-mm, …], "s": {"PETR4": {"c": [close…], "a": [adj…]}},
   "ret": {"PETR4": {"p1a","p3a","p5a","p10a","t1a","t3a","t5a","t10a","volAno","quedaMax"}},
   "falhas": {"QVQP3": "404"}}
"""
import datetime as dt
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

BASE = Path(__file__).parent
DATA = BASE / "data"
OUT_FILE = DATA / "precos_longo.json"
DATA.mkdir(exist_ok=True)

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
# sem UA de navegador o endpoint chart devolve 429 na primeira chamada
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")}
CONC = 4
# referências guardadas junto (mesma série, mesmo eixo de tempo)
REFS = ["^BVSP", "^GSPC", "BRL=X"]


def log(*a):
    print("[precos]", *a, file=sys.stderr)


def simbolos():
    """Todos os tickers do universo B3 + ETFs das watchlists + referências."""
    import re
    TICKER_RE = re.compile(r"^[A-Z0-9]{4}(3|4|5|6|11)$")
    syms = {}
    try:
        b3 = json.loads((DATA / "b3_companies.json").read_text(encoding="utf-8"))
        for c in b3.get("companies") or []:
            for cod in (c.get("codes") or []):
                cod = (cod or "").strip().upper()
                if TICKER_RE.match(cod):
                    syms[cod + ".SA"] = cod
    except Exception as e:
        log("b3_companies.json ilegível:", repr(e))
        sys.exit(1)
    try:
        wl = json.loads((DATA / "watchlists.json").read_text(encoding="utf-8"))
        for cat in (wl.get("etfs_b3") or {}).values():
            for e in cat:
                t = e["t"].strip().upper()
                syms[t + ".SA"] = t
        for k in ("us_indices", "us_etfs", "us_stocks"):
            for e in wl.get(k) or []:
                syms[e["t"].strip()] = e["t"].strip()
    except Exception as e:
        log("watchlists.json ilegível (segue sem ETFs):", repr(e))
    for r in REFS:
        syms.setdefault(r, r)
    return syms


def busca(ses, ysym):
    """(meses, close, adjclose) ou (None, motivo)."""
    for tent in (1, 2, 3):
        try:
            r = ses.get(CHART.format(sym=ysym.replace("^", "%5E")),
                        params={"range": "10y", "interval": "1mo"}, timeout=(6, 25))
            if r.status_code == 404:
                return None, "404 (papel inexistente ou renomeado no Yahoo)"
            if r.status_code == 429:
                time.sleep(8 * tent)
                continue
            r.raise_for_status()
            res = (r.json().get("chart") or {}).get("result") or []
            if not res:
                return None, "resposta sem série"
            x = res[0]
            ts = x.get("timestamp") or []
            q = ((x.get("indicators") or {}).get("quote") or [{}])[0]
            aj = ((x.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
            cl = q.get("close") or []
            if not ts or not cl:
                return None, "sem timestamp/close"
            meses, cs, as_ = [], [], []
            for i, t in enumerate(ts):
                c = cl[i] if i < len(cl) else None
                a = aj[i] if i < len(aj) else None
                if c is None or c <= 0:
                    continue
                meses.append(dt.datetime.utcfromtimestamp(t).strftime("%Y-%m"))
                cs.append(round(float(c), 4))
                as_.append(round(float(a), 4) if a is not None and a > 0 else None)
            return (meses, cs, as_), None
        except Exception as e:
            if tent == 3:
                return None, repr(e)[:120]
            time.sleep(3 * tent)
    return None, "esgotou as tentativas"


def retornos(meses, cs, as_):
    """Retorno de preço e total por janela, volatilidade e queda máxima."""
    if len(cs) < 13:
        return None
    out = {}
    fim_c, fim_a = cs[-1], next((v for v in reversed(as_) if v), None)

    def por_janela(serie, prefixo):
        for anos, rot in ((1, "1a"), (3, "3a"), (5, "5a"), (10, "10a")):
            n = anos * 12
            if len(serie) <= n:
                continue
            ini = serie[len(serie) - 1 - n]
            fim = serie[-1]
            if ini is None or fim is None or ini <= 0:
                continue
            tot = fim / ini - 1
            # janelas de 1 ano ficam em retorno simples; acima disso, anualizado,
            # que é o número comparável entre janelas diferentes
            out[prefixo + rot] = round(100 * tot, 1) if anos == 1 else \
                round(100 * ((1 + tot) ** (1 / anos) - 1), 1)
        return out

    por_janela(cs, "p")
    aj = [v for v in as_ if v] if any(as_) else []
    if len(aj) >= 13:
        por_janela(aj, "t")
    # volatilidade anualizada dos retornos mensais dos últimos 3 anos
    base = (aj or cs)[-37:]
    rs = [base[i] / base[i - 1] - 1 for i in range(1, len(base)) if base[i - 1]]
    if len(rs) >= 24:
        m = sum(rs) / len(rs)
        var = sum((x - m) ** 2 for x in rs) / (len(rs) - 1)
        out["volAno"] = round(100 * math.sqrt(var) * math.sqrt(12), 1)
    # maior queda do topo ao fundo na série inteira (retorno total quando houver)
    serie = aj or cs
    topo, queda = serie[0], 0.0
    for v in serie:
        topo = max(topo, v)
        if topo > 0:
            queda = min(queda, v / topo - 1)
    out["quedaMax"] = round(100 * queda, 1)
    out["desde"] = meses[0]
    out["n"] = len(cs)
    return out or None


def main():
    syms = simbolos()
    lista = sorted(syms)
    log(f"{len(lista)} símbolos (inclui {len(REFS)} referências)")
    ses = requests.Session()
    ses.headers.update(UA)
    todos_meses, series, rets, falhas = set(), {}, {}, {}

    def uma(ysym):
        d, err = busca(ses, ysym)
        time.sleep(0.25)
        return ysym, d, err

    with ThreadPoolExecutor(max_workers=CONC) as ex:
        for i, (ysym, d, err) in enumerate(ex.map(uma, lista)):
            chave = syms[ysym]
            if not d:
                falhas[chave] = err
                continue
            meses, cs, as_ = d
            series[chave] = (meses, cs, as_)
            todos_meses.update(meses)
            r = retornos(meses, cs, as_)
            if r:
                rets[chave] = r
            if i % 100 == 0:
                log(f"{i}/{len(lista)} · {len(series)} ok · {len(falhas)} falhas")

    if len(series) < 150:
        log(f"apenas {len(series)} séries — abaixo do piso de 150; abortando sem gravar")
        sys.exit(1)

    # eixo de tempo único: todo papel é alinhado nele, com null onde não negociava
    eixo = sorted(todos_meses)
    pos = {m: i for i, m in enumerate(eixo)}
    s = {}
    for chave, (meses, cs, as_) in series.items():
        c = [None] * len(eixo)
        a = [None] * len(eixo)
        for j, m in enumerate(meses):
            k = pos[m]
            c[k] = cs[j]
            a[k] = as_[j]
        # se adjclose == close em toda a série, não vale gravar duas vezes
        s[chave] = {"c": c} if a == c else {"c": c, "a": a}

    snap = {
        "updatedAt": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fonte": "Yahoo Finance — chart v8, range=10y interval=1mo",
        "nota": ("'c' é o fechamento do mês como o mercado via (use para múltiplo "
                 "histórico); 'a' é o fechamento ajustado por provento e desdobramento "
                 "(use para retorno). Retorno de preço (p) e retorno total (t) são "
                 "publicados separados porque o Ibovespa é índice de preço: comparar "
                 "retorno total da ação com o índice infla a ação. Janelas de 3, 5 e 10 "
                 "anos são anualizadas; a de 1 ano é simples."),
        "meses": eixo,
        "s": s,
        "ret": rets,
        "falhas": falhas,
    }
    OUT_FILE.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    log(f"OK {OUT_FILE} ({OUT_FILE.stat().st_size/1024:.0f} KB) · {len(s)} séries · "
        f"{len(rets)} com retorno · {len(falhas)} sem série · eixo {eixo[0]}→{eixo[-1]}")
    for k in REFS:
        r = rets.get(k)
        if r:
            log(f"  referência {k}: preço 1a {r.get('p1a')}% · 5a {r.get('p5a')}%/ano · "
                f"10a {r.get('p10a')}%/ano")
    if falhas:
        log(f"  exemplos sem série: {', '.join(list(falhas)[:8])}")


if __name__ == "__main__":
    main()
