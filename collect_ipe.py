#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fatos relevantes, comunicados ao mercado, avisos aos acionistas e o calendário
oficial de eventos corporativos — direto do IPE da CVM.

Por que existe: o painel já tem manchete de imprensa (`collect_news.py`), que é
jornalismo. O IPE é o REGISTRO REGULATÓRIO: o documento que a companhia
protocolou, com data de entrega, categoria e link para o PDF no sistema da CVM.
Para quem assessora cliente, é a diferença entre "saiu no jornal" e "consta".

Fonte: https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_<ano>.zip
(1,6 MB em 2026; um único CSV dentro, latin-1, separador ';', 13 colunas).

## O que foi medido em 11/09/2026, e por que cada guarda existe

* **O arquivo é reescrito aos DOMINGOS, não diariamente.** Todos os conjuntos da
  CVM (IPE, ITR, DFP, FRE) tinham o mesmo `Last-Modified`: domingo 06/09, ~10h
  GMT — cinco dias de atraso. Fato relevante de terça não aparece aqui antes do
  domingo seguinte. O arquivo publica a data do documento mais recente que
  encontrou (`ate`) e a tela diz isso em vez de fingir que está ao vivo.
* **O arquivo do ano ANTERIOR continua mudando**: o de 2025 foi reescrito na
  mesma leva de setembro de 2026. Por isso os dois anos são reprocessados sempre.
* **`Codigo_CVM` vem SEM zero à esquerda** (9512), enquanto o ITR/DFP e a B3
  usam seis dígitos (009512). A chave aqui é o inteiro, e a página normaliza.
* **`Data_Referencia` tem data impossível**: 9 linhas em 2026 trazem 3026-04-30
  (Metalfrio, Betapart), 2926-03-27 (Embraer), 2029-06-29 (Vale). Só entram datas
  dentro de uma faixa plausível; a data que manda é a de ENTREGA, que é protocolo.
* **O calendário de eventos é reapresentado o tempo todo**: das 464 entregas de
  2026, a maioria é "RE – Reapresentação Espontânea", com até 10 versões da mesma
  empresa. Só a versão mais recente de cada (empresa, exercício) é publicada.

## O link

`Link_Download` aponta para `frmDownloadDocumento.aspx` com três parâmetros
numéricos (`numProtocolo`, `numSequencia`, `numVersao`). O arquivo guarda só os
três números e a página remonta o endereço — 153 bytes viram 12 e o arquivo cabe.
Medido: um GET nesse endereço devolve o PDF (`%PDF-1.7`, Content-disposition
attachment). O endpoint é instável: já respondeu página de erro ASP.NET para o
mesmo endereço que minutos depois devolveu o PDF. A página avisa que é um
endereço da CVM que pode pedir nova tentativa, em vez de prometer que abre.
"""
import datetime as dt
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import requests

BASE = Path(__file__).parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
OUT_FILE = DATA / "ipe.json"

HOJE = dt.date.today()
ANOS = [HOJE.year - 1, HOJE.year]
URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip"
UA = {"User-Agent": "Mozilla/5.0 (painel-b3; uso educacional/interno; contato via repo)"}
S = requests.Session()
S.headers.update(UA)

# A ordem é a do arquivo publicado: a página guarda o índice, não o texto.
# Ficam de fora de propósito as categorias de alto volume e baixo valor de
# leitura — "Valores Mobiliários negociados e detidos" (6.131 registros em 2026,
# a movimentação de insider, que tem arquivo próprio no VLMO), "Assembleia"
# (6.543) e "Reunião da Administração" (5.117), que são atas de rito.
CATEGORIAS = [
    "Fato Relevante",
    "Comunicado ao Mercado",
    "Aviso aos Acionistas",
    "Calendário de Eventos Corporativos",
]
CAT_CALENDARIO = 3
MAX_POR_EMPRESA = 150        # a Petrobras entrega 234 em dois anos; o resto é cauda
MAX_ASSUNTO = 160
ANO_MIN, ANO_MAX = 2015, HOJE.year + 1
RE_LINK = re.compile(r"numProtocolo=(\d+).*?numSequencia=(\d+).*?numVersao=(\d+)")


def log(*a):
    print("[ipe]", *a, file=sys.stderr)


def data_ok(s):
    """Data no formato AAAA-MM-DD e dentro de uma faixa plausível."""
    if not s or len(s) != 10 or s[4] != "-":
        return None
    try:
        ano = int(s[:4])
    except ValueError:
        return None
    if not (ANO_MIN <= ano <= ANO_MAX):
        return None
    return s


def baixa(ano):
    try:
        r = S.get(URL.format(ano=ano), timeout=180)
    except Exception as e:                                   # noqa: BLE001
        log(f"ANO {ano}: falhou o download ({e})")
        return []
    if r.status_code != 200 or len(r.content) < 50_000:
        log(f"ANO {ano}: HTTP {r.status_code}, {len(r.content)} bytes — ignorado")
        return []
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    alvo = f"ipe_cia_aberta_{ano}.csv"
    if alvo not in zf.namelist():
        log(f"ANO {ano}: {alvo} não está no zip ({zf.namelist()[:3]})")
        return []
    with zf.open(alvo) as fh:
        txt = fh.read().decode("latin-1")
    linhas = [l for l in txt.splitlines() if l.strip()]
    if not linhas:
        return []
    cab = linhas[0].split(";")
    fora = []
    for l in linhas[1:]:
        v = l.split(";")
        if len(v) != len(cab):
            continue
        fora.append(dict(zip(cab, v)))
    log(f"ANO {ano}: {len(r.content)/1024:.0f} KB · {len(fora)} registros")
    return fora


def main():
    registros = []
    for ano in ANOS:
        registros.extend(baixa(ano))
    if len(registros) < 5_000:
        log(f"ABORTA: só {len(registros)} registros — esperado dezenas de milhares")
        sys.exit(1)

    por_cvm = {}
    calendario = {}
    ate = ""
    descartes = {"categoria": 0, "data": 0, "link": 0}
    for r in registros:
        cat = (r.get("Categoria") or "").strip()
        if cat not in CATEGORIAS:
            descartes["categoria"] += 1
            continue
        dent = data_ok((r.get("Data_Entrega") or "").strip())
        if not dent:
            descartes["data"] += 1
            continue
        m = RE_LINK.search((r.get("Link_Download") or "").replace("&amp;", "&"))
        if not m:
            descartes["link"] += 1
            continue
        try:
            cvm = str(int(r.get("Codigo_CVM") or 0))
        except ValueError:
            continue
        if cvm == "0":
            continue
        ci = CATEGORIAS.index(cat)
        assunto = " ".join((r.get("Assunto") or "").split())[:MAX_ASSUNTO]
        versao = int(m.group(3))
        item = [ci, dent, assunto, int(m.group(1)), int(m.group(2)), versao]
        dref = data_ok((r.get("Data_Referencia") or "").strip())
        if dref and dref != dent:
            item.append(dref)
        ate = max(ate, dent)

        if ci == CAT_CALENDARIO:
            # o calendário é reapresentado à exaustão: só a versão mais nova de
            # cada (empresa, exercício) vale, senão a tela lista dez vezes o
            # mesmo documento
            chave = (cvm, dref or dent[:4])
            ant = calendario.get(chave)
            if ant is None or (dent, versao) > (ant[1], ant[5]):
                calendario[chave] = item
            continue
        por_cvm.setdefault(cvm, []).append(item)

    for (cvm, _), item in calendario.items():
        por_cvm.setdefault(cvm, []).append(item)

    # do mais recente para o mais antigo, e com teto por empresa
    cortadas = 0
    for cvm, lst in por_cvm.items():
        lst.sort(key=lambda x: (x[1], x[5]), reverse=True)
        if len(lst) > MAX_POR_EMPRESA:
            cortadas += 1
            del lst[MAX_POR_EMPRESA:]

    if not ate:
        log("ABORTA: nenhum documento com data de entrega válida")
        sys.exit(1)
    atraso = (HOJE - dt.date.fromisoformat(ate)).days
    saida = {
        "updatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fonte": "CVM · IPE (Informações Periódicas e Eventuais)",
        "cats": CATEGORIAS,
        "ate": ate,
        "atrasoDias": atraso,
        "nota": "O conjunto da CVM é reescrito uma vez por semana, aos domingos. "
                "O documento mais recente deste arquivo é de " + ate + ", "
                + str(atraso) + " dia(s) atrás. Fato relevante divulgado depois disso "
                "ainda não consta aqui — para o que acabou de sair, veja as notícias.",
        "anos": ANOS,
        "resumo": {"empresas": len(por_cvm),
                   "documentos": sum(len(v) for v in por_cvm.values()),
                   "calendarios": len(calendario),
                   "empresasCortadas": cortadas,
                   "descartes": descartes},
        "porCvm": por_cvm,
    }
    OUT_FILE.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"OK {OUT_FILE} ({OUT_FILE.stat().st_size/1024:.0f} KB) · {len(por_cvm)} empresas · "
        f"{saida['resumo']['documentos']} documentos · {len(calendario)} calendários oficiais · "
        f"último documento em {ate} ({atraso} dias atrás)")


if __name__ == "__main__":
    main()
