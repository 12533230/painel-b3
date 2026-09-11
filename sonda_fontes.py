#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sonda de fontes novas — NÃO publica dado, só diz se a fonte responde do runner.

Por que existe: todas as fontes novas (B3 listada, B3 índices, Yahoo, FRE da CVM)
foram medidas de um IP residencial brasileiro. Os endpoints `sistemaswebb3-listados`
e `bvmf.bmfbovespa` ficam atrás de Cloudflare, e o pipeline nunca falou com eles —
IP de datacenter é justamente onde o Reddit devolveu 403 por 20 dias sem ninguém
perceber. Então antes de acoplar qualquer número ao painel, esta sonda roda no
GitHub Actions e registra: status HTTP, tamanho, tempo e UM registro de exemplo.

Sai 0 sempre que conseguir gerar o relatório; quem decide o que fazer é quem lê.
O workflow marca a execução como falha se alguma fonte OBRIGATÓRIA cair (as que já
estão em uso hoje), para não confundir "estreia bloqueada" com "regressão".
"""
import base64
import datetime as dt
import io
import json
import re
import sys
import time
import zipfile

import requests

UA_ROBO = "Mozilla/5.0 (painel-b3; uso educacional/interno; contato via repo)"
UA_NAV = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

B3L = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall"
B3I = "https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall"
YCHART = "https://query1.finance.yahoo.com/v8/finance/chart"

linhas = []
falhas_obrigatorias = 0


def p(*a):
    linhas.append(" ".join(str(x) for x in a))
    print(*a)


def b64(o):
    return base64.b64encode(json.dumps(o).encode()).decode()


def sonda(nome, url, obrigatoria=False, ua=UA_ROBO, timeout=45, amostra=None, head=False):
    """Faz 1 requisição e registra o resultado. `amostra` recebe o response."""
    global falhas_obrigatorias
    t0 = time.time()
    try:
        r = requests.request("HEAD" if head else "GET", url,
                             headers={"User-Agent": ua}, timeout=timeout)
        ms = int((time.time() - t0) * 1000)
        tam = int(r.headers.get("content-length") or len(r.content or b""))
        srv = r.headers.get("server", "?")
        cf = r.headers.get("cf-ray", "")
        ok = 200 <= r.status_code < 300
        p(f"  [{'OK ' if ok else 'ERRO'}] {nome}")
        p(f"        HTTP {r.status_code} · {tam} bytes · {ms} ms · server={srv}"
          + (f" · cf-ray={cf}" if cf else ""))
        if not ok:
            p(f"        corpo: {(r.text or '')[:200]!r}")
            if obrigatoria:
                falhas_obrigatorias += 1
            return None
        if amostra:
            try:
                for ln in amostra(r):
                    p(f"        {ln}")
            except Exception as e:
                p(f"        AVISO: resposta 200 mas não deu para interpretar: {e!r}")
                if obrigatoria:
                    falhas_obrigatorias += 1
        return r
    except Exception as e:
        p(f"  [ERRO] {nome}")
        p(f"        exceção: {e!r}")
        if obrigatoria:
            falhas_obrigatorias += 1
        return None


# ---------------------------------------------------------------- amostras
def am_indices(r):
    d = r.json()
    res = d.get("results") or []
    idx = sorted({i for x in res for i in (x.get("indexes") or "").split(",") if i})
    yield f"totalRecords={((d.get('page') or {}).get('totalRecords'))} · tickers={len(res)} · índices distintos={len(idx)}"
    yield f"header={json.dumps(d.get('header'), ensure_ascii=False)[:160]}"
    if res:
        yield f"exemplo={json.dumps(res[0], ensure_ascii=False)[:200]}"
    # a prova que interessa: o IBOV sai daqui igual ao GetPortfolioDay?
    ibov = [x.get("code") for x in res if "IBOV" in (x.get("indexes") or "")]
    yield f"papéis com IBOV nesta resposta: {len(ibov)} (ex.: {', '.join(sorted(ibov)[:6])})"


def am_carteira(r):
    d = r.json()
    res = d.get("results") or []
    yield f"data da carteira={((d.get('header') or {}).get('date'))} · papéis={len(res)}"
    if res:
        yield f"exemplo={json.dumps(res[0], ensure_ascii=False)[:200]}"


def am_div(r):
    d = r.json()
    pg = d.get("page") or {}
    res = d.get("results") or []
    yield f"totalRecords={pg.get('totalRecords')} totalPages={pg.get('totalPages')} nesta página={len(res)}"
    if res:
        yield f"exemplo={json.dumps(res[0], ensure_ascii=False)[:260]}"
    else:
        yield "SEM REGISTROS — conferir o tradingName (o match é exato e '/' quebra a busca)"


def am_div_grande(r):
    """pageSize acima de 100 devolve 200 com corpo vazio — a falha é silenciosa."""
    corpo = r.content or b""
    d = None
    try:
        d = r.json()
    except Exception:
        pass
    pg = (d or {}).get("page") or {}
    yield (f"corpo={len(corpo)} bytes · totalRecords={pg.get('totalRecords')} · "
           f"results={len((d or {}).get('results') or [])}")
    yield ("CONFIRMA a armadilha do pageSize>100 (200 com corpo curto e totalRecords nulo)"
           if len(corpo) < 500 or pg.get("totalRecords") is None
           else "ATENÇÃO: pageSize>100 respondeu com dado — a armadilha pode ter mudado")


def am_supl(r):
    d = r.json()
    o = d[0] if isinstance(d, list) and d else d
    if not isinstance(o, dict):
        yield f"formato inesperado: {str(d)[:160]}"
        return
    cd = o.get("cashDividends") or []
    sd = o.get("stockDividends") or []
    yield (f"tradingName={o.get('tradingName')} codeCVM={o.get('codeCVM')} "
           f"ON={o.get('numberCommonShares')} PN={o.get('numberPreferredShares')} "
           f"total={o.get('totalNumberShares')}")
    yield f"cashDividends={len(cd)} · stockDividends={len(sd)}"
    if cd:
        yield f"exemplo provento={json.dumps(cd[0], ensure_ascii=False)[:220]}"
    if sd:
        yield f"exemplo desdobramento={json.dumps(sd[0], ensure_ascii=False)[:200]}"


def am_yahoo(r):
    d = r.json()
    res = (d.get("chart") or {}).get("result") or []
    if not res:
        yield f"sem result: {json.dumps(d)[:200]}"
        return
    x = res[0]
    ts = x.get("timestamp") or []
    q = ((x.get("indicators") or {}).get("quote") or [{}])[0]
    aj = ((x.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
    meta = x.get("meta") or {}
    yield (f"pontos={len(ts)} · moeda={meta.get('currency')} · "
           f"1º negócio={dt.datetime.utcfromtimestamp(meta.get('firstTradeDate') or 0):%Y-%m-%d}")
    cl = [v for v in (q.get("close") or []) if v is not None]
    if cl and ts:
        yield (f"close: {cl[0]} ({dt.datetime.utcfromtimestamp(ts[0]):%Y-%m}) → "
               f"{cl[-1]} ({dt.datetime.utcfromtimestamp(ts[-1]):%Y-%m})")
    if aj:
        a = [v for v in aj if v is not None]
        if a:
            yield f"adjclose: {a[0]} → {a[-1]}  (usar ESTE para retorno, o close para P/L histórico)"
    ev = (x.get("events") or {}).get("dividends") or {}
    yield f"eventos de dividendo na janela={len(ev)}"


def am_fre(r):
    z = zipfile.ZipFile(io.BytesIO(r.content))
    nomes = z.namelist()
    yield f"zip com {len(nomes)} arquivos"
    for alvo in ("distribuicao_capital", "posicao_acionaria"):
        n = [x for x in nomes if alvo in x]
        if not n:
            yield f"  {alvo}: AUSENTE"
            continue
        with z.open(n[0]) as f:
            bruto = f.read()
        txt = bruto.decode("latin1").splitlines()
        yield f"  {n[0]}: {len(bruto)} bytes · {len(txt)-1} linhas"
        if txt:
            yield f"    colunas: {txt[0][:300]}"
        if len(txt) > 1:
            yield f"    1ª linha: {txt[1][:260]}"


def am_cotahist(r):
    yield (f"content-length={r.headers.get('content-length')} · "
           f"accept-ranges={r.headers.get('accept-ranges')} · "
           f"last-modified={r.headers.get('last-modified')}")


def main():
    p(f"=== sonda de fontes · {dt.datetime.utcnow():%Y-%m-%dT%H:%M:%SZ} · "
      f"runner do GitHub Actions (IP de datacenter)")
    p("")
    p("Objetivo: dizer se cada fonte responde DAQUI. Medições anteriores saíram de IP")
    p("residencial no Brasil; B3 e bvmf estão atrás de Cloudflare e são estreia para o")
    p("pipeline. Nada aqui é publicado no painel.")
    p("")

    p("--- 1. fontes JÁ EM USO (se alguma cair aqui, é regressão) ---")
    sonda("CVM ITR 2026 (zip, HEAD)",
          "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_2026.zip",
          obrigatoria=True, head=True, amostra=am_cotahist)
    sonda("Fundamentus — tabela de múltiplos",
          "https://www.fundamentus.com.br/resultado.php", obrigatoria=True,
          amostra=lambda r: [f"linhas <tr>={len(re.findall(r'<tr', r.text))} · "
                             f"encoding={r.encoding}"])
    sonda("Yahoo spark (cotações do robô)",
          "https://query1.finance.yahoo.com/v7/finance/spark?symbols=PETR4.SA,VALE3.SA&range=1d&interval=30m",
          obrigatoria=True,
          amostra=lambda r: [f"resultados={len(((r.json().get('spark') or {}).get('result')) or [])}"])
    sonda("B3 empresas listadas (refresh_b3)",
          f"{B3L}/GetDetail/{b64({'codeCVM': '9512', 'language': 'pt-br'})}",
          obrigatoria=True,
          amostra=lambda r: [f"tradingName={r.json().get('tradingName')} · "
                             f"issuer={r.json().get('issuingCompany')}"])
    p("")

    p("--- 2. ESTREIA: índices da B3 ---")
    sonda("GetStockIndex (1 chamada → ticker × índices)",
          f"{B3I}/GetStockIndex/{b64({'language': 'pt-br'})}", amostra=am_indices)
    sonda("GetPortfolioDay IBOV (peso por papel)",
          f"{B3I}/GetPortfolioDay/{b64({'language': 'pt-br', 'pageNumber': 1, 'pageSize': 120, 'index': 'IBOV', 'segment': '1'})}",
          amostra=am_carteira)
    sonda("GetPortfolioDay SMLL (a sigla é SMLL, não SMAL)",
          f"{B3I}/GetPortfolioDay/{b64({'language': 'pt-br', 'pageNumber': 1, 'pageSize': 200, 'index': 'SMLL', 'segment': '1'})}",
          amostra=am_carteira)
    p("")

    p("--- 3. ESTREIA: proventos da B3 ---")
    sonda("GetListedCashDividends PETROBRAS (pageSize=100, o máximo)",
          f"{B3L}/GetListedCashDividends/{b64({'language': 'pt-br', 'pageNumber': 1, 'pageSize': 100, 'tradingName': 'PETROBRAS'})}",
          amostra=am_div)
    sonda("GetListedCashDividends AMBEV S.A. (o '/' tem de ser removido)",
          f"{B3L}/GetListedCashDividends/{b64({'language': 'pt-br', 'pageNumber': 1, 'pageSize': 100, 'tradingName': 'AMBEV S.A.'.replace('/', '')})}",
          amostra=am_div)
    sonda("GetListedCashDividends pageSize=500 (deve falhar em silêncio)",
          f"{B3L}/GetListedCashDividends/{b64({'language': 'pt-br', 'pageNumber': 1, 'pageSize': 500, 'tradingName': 'PETROBRAS'})}",
          amostra=am_div_grande)
    sonda("GetListedSupplementCompany PETR (paymentDate + desdobramentos + nº de ações)",
          f"{B3L}/GetListedSupplementCompany/{b64({'issuingCompany': 'PETR', 'language': 'pt-br'})}",
          amostra=am_supl)
    p("")

    p("--- 4. ESTREIA: histórico longo de preço ---")
    sonda("Yahoo chart 10 anos mensal (UA de navegador)",
          f"{YCHART}/PETR4.SA?range=10y&interval=1mo&events=div%7Csplit",
          ua=UA_NAV, amostra=am_yahoo)
    sonda("Yahoo chart 10 anos mensal (UA do robô — pode dar 429)",
          f"{YCHART}/VALE3.SA?range=10y&interval=1mo", amostra=am_yahoo)
    sonda("Yahoo chart ^BVSP (referência do índice)",
          f"{YCHART}/%5EBVSP?range=10y&interval=1mo", ua=UA_NAV, amostra=am_yahoo)
    sonda("COTAHIST anual 2025 (HEAD — só o tamanho)",
          "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A2025.ZIP",
          head=True, amostra=am_cotahist)
    p("")

    p("--- 5. ESTREIA: FRE da CVM (free float e acionistas) ---")
    sonda("FRE 2026 (zip completo)",
          "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_2026.zip",
          timeout=180, amostra=am_fre)
    p("")

    p("--- 6. ESTREIA: DFP antiga (série longa) ---")
    for ano in (2010, 2015):
        sonda(f"DFP {ano} (HEAD)",
              f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip",
              head=True, amostra=am_cotahist)
    p("")

    p("--- 7. fonte descartada como VALOR (só sanity check) ---")
    p("  Yahoo events=div não serve para exibir dividendo: medido em 10/09/2026,")
    p("  ITUB4 soma 2,6458 em 12 meses contra 3,1653 na B3 e no Fundamentus (16% a")
    p("  menos, perde JCP mensais pequenos). Fica como conferência, não como número.")
    p("")
    p(f"=== fim da sonda · falhas em fonte obrigatória: {falhas_obrigatorias}")


if __name__ == "__main__":
    main()
    with open("sonda.log", "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    # o código de saída fala só das fontes que já estão em produção
    sys.exit(1 if falhas_obrigatorias else 0)
