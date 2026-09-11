#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Histórico de proventos por papel (dividendos, JCP, rendimentos) — fonte B3.

Fonte primária: `listedCompaniesProxy/CompanyCall/GetListedCashDividends`, que
devolve o histórico completo por empresa (a Petrobras tem 343 registros desde
1996; o Itaú, 956). Complemento: `GetListedSupplementCompany`, a única rota que
traz **data de pagamento**, o exercício a que o provento se refere e os
**eventos de desdobramento/grupamento**.

ARMADILHAS, todas medidas em 10/09/2026 desta máquina — cada uma virou guarda:

1. **`pageSize` acima de 100 falha em SILÊNCIO.** Com 500, a resposta é
   HTTP 200 com 91 bytes e `totalRecords: null`. Quem não conferir o corpo
   conclui "empresa sem provento". Aqui o pageSize é fixo em 100 e a paginação
   vai até `totalPages`.
2. **`/` no nome quebra a busca.** `tradingName: "KLABIN S/A"` devolve 0
   registros; `"KLABIN SA"` devolve 219. O match é exato, então o nome vai
   sempre com `replace("/", "")`. Sem isso, empresas grandes apareceriam como
   "não paga dividendo" — número errado por omissão.
3. **Registro antigo é por LOTE DE MIL.** O dividendo de 21/03/1996 da
   Petrobras PN vem `valueCash: "5,1471"` com `quotedPerShares: "1000"`. Sem
   dividir, o histórico mostra dividendo mil vezes maior. Todo valor é dividido
   por `quotedPerShares`.
4. **NÃO deduplicar linhas iguais.** Parece erro da B3 repetir o mesmo valor na
   mesma data, mas são pagamentos distintos: a WEG tem **três** linhas de
   `DIVIDENDO 0,412832` com data-com 19/12/2025, e é somando as três que o
   resultado casa com o mercado — 3,86% contra 3,81% do Fundamentus, erro de
   1,3%. Com deduplicação o DY da WEG caía para 2,27% (erro de 40%). Medido na
   amostra de 58 papéis: sem dedup o erro mediano contra o Fundamentus cai de
   2,1% para **1,3%** e os papéis dentro de 10% sobem de 41 para **47**.
5. **A ordem não é a da data-com.** O 1º registro do Itaú é aprovado em
   09/12/2025 com data-com em 31/08/2026. Ordenamos pela data-com.
6. **Desdobramento não é aplicado.** O supplement da Petrobras traz
   `DESDOBRAMENTO factor "100,00000000000"` em 25/04/2008, e não está
   documentado se 100 significa "100%" (1 vira 2) ou "100 vezes". Como a
   diferença muda o número por 50×, o painel **lista o evento** com o fator
   exatamente como a B3 dá e **não ajusta** valor antigo. O que é publicado como
   indicador é só a soma dos **últimos 12 meses**, janela em que um evento
   dessa ordem é raro — e quando houver um, o papel sai marcado.
7. **UNIT não tem provento por classe.** A B3 entrega ON/PN, nunca a UNIT
   (TAEE11, KLBN11, SANB11). Em vez de somar classes por uma proporção que a
   API não fornece, a UNIT fica registrada como "sem dado por classe".

Saída: `data/proventos.json`
  {"updatedAt", "porTicker": {"PETR4": {"n": 171, "eventos": [[data-com, valor,
   tipo, data-pag, aprovado], …], "d12": 3.6554, "d12de": "…", "eventosSocietarios": […]}}}
"""
import base64
import datetime as dt
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

BASE = Path(__file__).parent
DATA = BASE / "data"
OUT_FILE = DATA / "proventos.json"
DATA.mkdir(exist_ok=True)

API = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall"
UA = {"User-Agent": "Mozilla/5.0 (painel-b3; uso educacional/interno; contato via repo)"}
PAGE = 100          # máximo real; acima disso a resposta vem vazia com HTTP 200
CONC = 6            # 351 empresas em ~4 s medidos; mantém educado com o endpoint
HOJE = dt.date.today()

# classe da B3 -> sufixo do ticker
SUFIXO = {"ON": "3", "PN": "4", "PNA": "5", "PNB": "6", "PNC": "7", "PND": "8"}
TIPO = {"DIVIDENDO": "DIV", "JRS CAP PROPRIO": "JCP", "RENDIMENTO": "REND",
        "REST CAP DIN": "RESTCAP", "BONIFICACAO": "BONIF"}


def log(*a):
    print("[proventos]", *a, file=sys.stderr)


def b64(o):
    return base64.b64encode(json.dumps(o).encode()).decode()


def num(s):
    """'0,67407131' -> 0.67407131 · '' -> None"""
    if s is None:
        return None
    t = str(s).strip().replace(".", "").replace(",", ".") if "," in str(s) else str(s).strip()
    try:
        return float(t)
    except ValueError:
        return None


def data_iso(s):
    """'21/08/2026' -> '2026-08-21'. Sentinela '31/12/9999' -> None."""
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", str(s or "").strip())
    if not m:
        return None
    d, mo, y = m.groups()
    if y == "9999":          # 'sem data definida' — não é data futura
        return None
    return f"{y}-{mo}-{d}"


def chama(rota, params, tentativas=3, ses=None):
    s = ses or requests
    url = f"{API}/{rota}/{b64(params)}"
    for i in range(1, tentativas + 1):
        try:
            r = s.get(url, headers=UA, timeout=40)
            r.raise_for_status()
            if not r.content or len(r.content) < 40:
                # 200 com corpo vazio: é a falha silenciosa do endpoint
                raise RuntimeError(f"corpo de {len(r.content)} bytes")
            return r.json()
        except Exception as e:
            if i == tentativas:
                log(f"{rota} {list(params.values())[-1]!r}: {e!r}")
                return None
            time.sleep(3 * i)
    return None


def universo():
    b3 = json.loads((DATA / "b3_companies.json").read_text(encoding="utf-8"))
    TICKER_RE = re.compile(r"^[A-Z0-9]{4}(3|4|5|6|11)$")
    out = []
    for c in b3["companies"]:
        trad = (c.get("trad") or c.get("name") or "").strip()
        raiz = (c.get("issuer") or "").strip()
        tickers = sorted({t for t in (c.get("codes") or []) if TICKER_RE.match(t)})
        if not trad or not tickers or not c.get("codeCVM"):
            continue
        out.append({"trad": trad, "busca": trad.replace("/", ""), "raiz": raiz,
                    "cvm": str(int(c["codeCVM"])), "tickers": tickers})
    return out


def historico(emp, ses):
    """Todas as páginas de GetListedCashDividends de uma empresa, normalizadas."""
    p1 = chama("GetListedCashDividends",
               {"language": "pt-br", "pageNumber": 1, "pageSize": PAGE,
                "tradingName": emp["busca"]}, ses=ses)
    if not p1:
        return None, "sem resposta"
    pg = p1.get("page") or {}
    total = pg.get("totalRecords")
    if total is None:
        # exatamente o sintoma do pageSize inválido; com 100 não deve ocorrer
        return None, "totalRecords nulo (resposta vazia com HTTP 200)"
    linhas = list(p1.get("results") or [])
    tp = int(pg.get("totalPages") or 1)
    for n in range(2, tp + 1):
        d = chama("GetListedCashDividends",
                  {"language": "pt-br", "pageNumber": n, "pageSize": PAGE,
                   "tradingName": emp["busca"]}, ses=ses)
        if not d:
            return None, f"página {n} de {tp} falhou — histórico incompleto, descartado"
        linhas += list(d.get("results") or [])
    evs = []
    for x in linhas:
        classe = (x.get("typeStock") or "").strip().upper()
        dcom = data_iso(x.get("lastDatePriorEx"))
        aprov = data_iso(x.get("dateApproval"))
        bruto = num(x.get("valueCash"))
        lote = num(x.get("quotedPerShares")) or 1.0
        acao = (x.get("corporateAction") or "").strip().upper()
        if bruto is None or not classe:
            continue
        # sem deduplicação: linha repetida é pagamento repetido, não erro (ver item 4
        # do cabeçalho — a WEG prova, e o Fundamentus confirma a soma das três)
        evs.append({"classe": classe, "dcom": dcom, "aprov": aprov,
                    "v": bruto / lote if lote else bruto,
                    "lote": lote, "tipo": TIPO.get(acao, acao)})
    evs.sort(key=lambda e: (e["dcom"] or e["aprov"] or "", e["classe"]))
    return evs, None


def suplemento(emp, ses):
    """paymentDate/relatedTo dos ~12 meses recentes + eventos societários."""
    d = chama("GetListedSupplementCompany",
              {"issuingCompany": emp["raiz"], "language": "pt-br"}, ses=ses)
    o = (d[0] if isinstance(d, list) and d else d) or {}
    if not isinstance(o, dict):
        return {}, [], None
    # a raiz de 4 letras pode colidir entre empresas: só aceita se o cadastro casar
    if str(o.get("codeCVM") or "").lstrip("0") not in ("", emp["cvm"].lstrip("0")):
        return {}, [], f"raiz {emp['raiz']} devolveu codeCVM {o.get('codeCVM')} — ignorado"
    pag = {}
    for x in (o.get("cashDividends") or []):
        k = (data_iso(x.get("lastDatePrior")), (x.get("label") or "").strip().upper())
        dp = data_iso(x.get("paymentDate"))
        if k[0] and dp:
            pag[k] = {"dpag": dp, "ref": (x.get("relatedTo") or "").strip()}
    soc = []
    for x in (o.get("stockDividends") or []):
        soc.append({"tipo": (x.get("label") or "").strip(),
                    "fator": (x.get("factor") or "").strip(),
                    "data": data_iso(x.get("lastDatePrior")),
                    "aprov": data_iso(x.get("approvedOn"))})
    soc.sort(key=lambda s: s["data"] or "")
    return pag, soc, None


def main():
    uni = universo()
    log(f"universo: {len(uni)} empresas com ticker")
    ses = requests.Session()
    ses.headers.update(UA)
    res, semDado, erros = {}, [], []

    def uma(emp):
        evs, err = historico(emp, ses)
        pag, soc, aviso = suplemento(emp, ses)
        return emp, evs, err, pag, soc, aviso

    with ThreadPoolExecutor(max_workers=CONC) as ex:
        for emp, evs, err, pag, soc, aviso in ex.map(uma, uni):
            if aviso:
                log(aviso)
            if err:
                erros.append({"empresa": emp["trad"], "motivo": err})
                continue
            if not evs:
                semDado.append(emp["trad"])
                continue
            # completa a data de pagamento onde o supplement souber
            for e in evs:
                p = pag.get((e["dcom"], "DIVIDENDO" if e["tipo"] == "DIV" else
                             "JRS CAP PROPRIO" if e["tipo"] == "JCP" else e["tipo"]))
                if p:
                    e["dpag"] = p["dpag"]
                    if p.get("ref"):
                        e["ref"] = p["ref"]
            porClasse = {}
            for e in evs:
                porClasse.setdefault(e["classe"], []).append(e)
            for classe, lista in porClasse.items():
                suf = SUFIXO.get(classe)
                if not suf:
                    continue
                tk = emp["raiz"] + suf
                if tk not in emp["tickers"]:
                    continue    # a classe existe no histórico mas o papel não é negociado
                corte = (HOJE - dt.timedelta(days=365)).isoformat()
                ult = [e for e in lista if (e["dcom"] or "") >= corte]
                d12 = round(sum(e["v"] for e in ult), 6) if ult else None
                # evento societário dentro da janela de 12 meses invalida a soma:
                # o valor por ação de antes do evento não é comparável ao preço de hoje
                soc12 = [s for s in soc if (s["data"] or "") >= corte]
                # HISTÓRICO PARADO = razão social trocada, não "empresa que parou de
                # pagar". Medido: "SUZANO" devolve 24 registros que terminam em 2004,
                # porque a companhia hoje é SUZANO S.A. e o histórico novo está sob
                # outro tradingName. Publicar d12=0 ou uma soma velha nesse caso seria
                # afirmar que a empresa não paga provento. Corte: 18 meses.
                ultimo = max((e["dcom"] or "") for e in lista)
                parado = ultimo < (HOJE - dt.timedelta(days=548)).isoformat()
                res[tk] = {
                    "classe": classe, "n": len(lista),
                    "de": lista[0]["dcom"] or lista[0]["aprov"],
                    "ate": ultimo,
                    "d12": None if (soc12 or parado) else d12,
                    "n12": len(ult),
                    "eventos": [[e["dcom"], round(e["v"], 8), e["tipo"],
                                 e.get("dpag"), e["aprov"],
                                 None if e["lote"] == 1 else e["lote"]] for e in lista],
                }
                if parado:
                    res[tk]["historicoParado"] = True
                    res[tk]["aviso12"] = (
                        f"o histórico da B3 para este papel termina em {ultimo} — provável "
                        f"troca de razão social (a busca é por nome exato). A soma de 12 "
                        f"meses não é publicada porque seria falsa; os eventos abaixo são "
                        f"os que a B3 devolve para o nome atual.")
                elif soc12:
                    res[tk]["aviso12"] = (
                        "houve " + ", ".join(f"{s['tipo'].lower()} em {s['data']}" for s in soc12)
                        + " nos últimos 12 meses — a soma por ação não é comparável ao preço "
                          "de hoje e não é publicada")
                if soc:
                    res[tk]["eventosSocietarios"] = soc
            # UNIT: a B3 não entrega provento de UNIT, e somar classes exigiria a
            # composição da UNIT, que esta API não fornece. Fica explícito.
            for tk in emp["tickers"]:
                if tk.endswith("11") and tk not in res:
                    res[tk] = {"classe": "UNT", "n": 0, "d12": None,
                               "semDadoPorClasse": True,
                               "aviso12": ("a B3 publica provento por classe (ON/PN), não por "
                                           "UNIT; somar as classes exigiria a composição da "
                                           "UNIT, que a API não fornece")}

    if not res:
        log("nenhum provento coletado — abortando sem gravar")
        sys.exit(1)
    comD12 = sum(1 for v in res.values() if v.get("d12"))
    snap = {
        "updatedAt": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fonte": ("B3 — GetListedCashDividends (histórico) e GetListedSupplementCompany "
                  "(data de pagamento e eventos societários)"),
        "nota": ("Valor por AÇÃO, já dividido pelo lote cotado da época (registros dos anos "
                 "1990 vêm por lote de mil). Desdobramentos e grupamentos são LISTADOS mas "
                 "NÃO aplicados aos valores antigos, porque a API não documenta se o fator "
                 "é percentual ou multiplicador. O único indicador publicado é a soma dos "
                 "últimos 12 meses, e ela é omitida quando houve evento societário na janela."),
        "janelaDias": 365,
        "porTicker": res,
        "semProvento": sorted(semDado),
        "erros": erros,
    }
    OUT_FILE.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    log(f"OK {OUT_FILE} ({OUT_FILE.stat().st_size/1024:.0f} KB) · {len(res)} papéis · "
        f"{comD12} com soma de 12 meses · {len(semDado)} sem provento · {len(erros)} erros")
    if erros:
        for e in erros[:10]:
            log(f"  erro: {e['empresa']} — {e['motivo']}")
    # a coleta não pode "melhorar" perdendo empresa: se despencar, é bloqueio
    if len(res) < 100:
        log(f"apenas {len(res)} papéis com provento — abaixo do piso de 100; "
            f"provável bloqueio do endpoint. Abortando para não publicar base furada.")
        sys.exit(1)


if __name__ == "__main__":
    main()
