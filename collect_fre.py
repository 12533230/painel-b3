#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Composição acionária e free float, do Formulário de Referência (FRE) da CVM.

Por que existe: "quem controla esta empresa?" e "quanto do capital está em
circulação?" são as duas perguntas que o painel não respondia, e são pré-requisito
de qualquer análise de governança — free float baixo é risco de liquidez e de
minoritário. A Analítica mostra isso; o painel não mostrava nada.

Por que NÃO dá para tirar da B3: medido em 10/09/2026, `GetDetail` não traz free
float, e `GetListedHolderCapital`, `GetListedCapitalDistribution`,
`GetListedStockCapital` e `GetListedHolder` são todos 404. O
`theoricalQty`/`totalNumberShares` do índice NÃO é proxy: erra −27,0 pp em PETR4
e −53,1 pp em KLBN11, porque conta só a classe que está no índice.

Fonte: https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_<ano>.zip
(8,1 MB em 2026). Três arquivos internos importam:

  * `distribuicao_capital`  — free float OFICIAL, declarado pela companhia, por
    classe e consolidado, mais a contagem de acionistas PF / PJ / institucionais.
    É o número que o formulário exige; não é derivado por nós.
  * `posicao_acionaria`     — a lista de acionistas com 5% ou mais, por classe.
  * `capital_social`        — o total de ações por classe, usado como DENOMINADOR
    e como teste de consistência.

## A armadilha do percentual (medida, não suposta)

O arquivo `posicao_acionaria` TEM colunas de percentual e elas NÃO servem. Na
Petrobras, a União Federal aparece com `Percentual_Acao_Ordinaria_Circulacao =
100,000000` — e a União detém 3.740.470.811 das 7.442.231.382 ON, ou seja 50,3%.
O percentual do arquivo é relativo ao AGRUPAMENTO do acionista (`ID_Acionista_
Relacionado`), não ao capital da companhia: aquela linha diz "a União detém 100%
do BNDES", não "a União detém 100% da Petrobras".

Portanto:
  1. só as linhas de TOPO entram (`ID_Acionista_Relacionado` vazio) — as demais
     descrevem a cadeia de controle DE um acionista, não da companhia;
  2. o percentual é sempre RECALCULADO como quantidade ÷ capital social;
  3. e só é publicado quando a conta FECHA: a soma das linhas de topo tem de bater
     com o capital social dentro de 2%. Medido em 11/09/2026 sobre as 652
     empresas do arquivo, 565 fecham dentro de 0,5% e 10 dentro de 2%; as 49 que
     divergem são quase todas subsidiárias não listadas (RUMO MALHA SUL declara
     113 trilhões de ações contra 7 trilhões de capital). Das 354 empresas do
     painel, 336 constam no FRE do ano corrente, 336 saem com composição
     acionária, 323 passam no teste do capital (e por isso saem com percentual) e
     294 saem com free float. As que não passam saem com as QUANTIDADES e sem
     percentual, dizendo por quê.

Validação independente: o free float da Petrobras sai ON 46,74% / PN 80,99% e
bate com o `GetListedSupplementCompany` da B3. Vale sai com 96,0% de float e
"nenhum controlador declarado", o que é o esperado para uma corporation.

O que sai: `data/fre.json`, lido SOB DEMANDA pela página (não entra no HTML).
"""
import datetime as dt
import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
OUT_FILE = DATA / "fre.json"

HOJE = dt.date.today()
# o FRE do ano corrente existe desde os primeiros meses do ano; o do ano anterior
# é o retrato de quem ainda não entregou. Dois anos cobrem todo mundo.
ANOS = [HOJE.year, HOJE.year - 1]
URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_{ano}.zip"
UA = {"User-Agent": "Mozilla/5.0 (painel-b3; uso educacional/interno; contato via repo)"}
S = requests.Session()
S.headers.update(UA)

# Ordem de preferência do denominador. "Integralizado" é o que existe de fato;
# 'Subscrito' e 'Emitido' entram só quando a companhia não declara o primeiro
# (medido: TIM, MARFRIG e BARDELLA só têm "Capital Emitido" no arquivo de 2026).
TIPOS_CAPITAL = ["Capital Integralizado", "Capital Subscrito", "Capital Emitido"]
TOL_FECHA = 0.02          # 2% de folga entre a soma dos acionistas e o capital
MAX_ACIONISTAS = 30       # a WEG declara 68 pessoas da família; o resto vira um agregado
# linhas que o formulário usa como marcador, não como acionista de verdade
ROTULO_OUTROS = "OUTROS"
ROTULO_TESOURARIA = "AÇÕES TESOURARIA"


def log(*a):
    print("[fre]", *a, file=sys.stderr)


def so_dig(s):
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def baixa(ano):
    url = URL.format(ano=ano)
    try:
        r = S.get(url, timeout=180)
    except Exception as e:                                  # noqa: BLE001
        log(f"ANO {ano}: falhou o download ({e})")
        return None
    if r.status_code != 200 or len(r.content) < 50_000:
        log(f"ANO {ano}: HTTP {r.status_code}, {len(r.content)} bytes — ignorado")
        return None
    log(f"ANO {ano}: {len(r.content)/1024/1024:.1f} MB")
    return zipfile.ZipFile(io.BytesIO(r.content))


def le(zf, nome, ano):
    alvo = f"fre_cia_aberta_{nome}_{ano}.csv"
    if alvo not in zf.namelist():
        log(f"  {alvo} não está no zip")
        return pd.DataFrame()
    with zf.open(alvo) as fh:
        df = pd.read_csv(fh, sep=";", encoding="latin1", dtype=str,
                         on_bad_lines="skip", low_memory=False)
    df["CNPJ"] = df["CNPJ_Companhia"].map(so_dig)
    # chave de recência: data de referência + versão, ambas como texto ordenável
    df["REC"] = df["Data_Referencia"].fillna("") + "|" + df["Versao"].fillna("0").str.zfill(3)
    return df


def num(v):
    """Número do CSV da CVM, tolerando vazio, '-' e vírgula decimal."""
    if v is None:
        return None
    t = str(v).strip().replace(",", ".")
    if t in ("", "-", "nan", "None"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def inteiro(v):
    x = num(v)
    return None if x is None else int(round(x))


def mais_recente(df):
    """Uma linha por empresa: a de maior (data de referência, versão)."""
    if df.empty:
        return {}
    idx = df.groupby("CNPJ")["REC"].idxmax()
    return {r["CNPJ"]: r for _, r in df.loc[idx].iterrows()}


def coleta_ano(ano):
    zf = baixa(ano)
    if zf is None:
        return {}
    dist = le(zf, "distribuicao_capital", ano)
    pos = le(zf, "posicao_acionaria", ano)
    cap = le(zf, "capital_social", ano)
    if dist.empty and pos.empty:
        return {}

    dist_r = mais_recente(dist)

    # capital social: melhor tipo disponível, na versão mais recente
    capital = {}
    if not cap.empty:
        for tipo in reversed(TIPOS_CAPITAL):     # do pior para o melhor, sobrescrevendo
            sub = cap[cap["Tipo_Capital"] == tipo]
            for cnpj, r in mais_recente(sub).items():
                on = inteiro(r.get("Quantidade_Acoes_Ordinarias")) or 0
                pn = inteiro(r.get("Quantidade_Acoes_Preferenciais")) or 0
                if on + pn > 0:
                    capital[cnpj] = {"on": on, "pn": pn, "tipo": tipo}

    # posição acionária: só as linhas de topo, na versão mais recente da empresa
    topo_por_cnpj = {}
    if not pos.empty:
        rec = pos.groupby("CNPJ")["REC"].max().to_dict()
        sem_rel = pos["ID_Acionista_Relacionado"].isna() | (pos["ID_Acionista_Relacionado"].astype(str).str.strip() == "")
        sub = pos[sem_rel]
        for cnpj, g in sub.groupby("CNPJ"):
            g = g[g["REC"] == rec.get(cnpj)]
            if not g.empty:
                topo_por_cnpj[cnpj] = g

    out = {}
    for cnpj in set(dist_r) | set(topo_por_cnpj):
        reg = {"ano": ano}
        d = dist_r.get(cnpj)
        if d is not None:
            reg["ref"] = d.get("Data_Referencia")
            reg["versao"] = inteiro(d.get("Versao"))
            reg["assembleia"] = d.get("Data_Ultima_Assembleia") or None
            reg["nome"] = d.get("Nome_Companhia")
            flt = {
                "on": num(d.get("Percentual_Acoes_Ordinarias_Circulacao")),
                "pn": num(d.get("Percentual_Acoes_Preferenciais_Circulacao")),
                "tot": num(d.get("Percentual_Total_Acoes_Circulacao")),
                "qon": inteiro(d.get("Quantidade_Acoes_Ordinarias_Circulacao")),
                "qpn": inteiro(d.get("Quantidade_Acoes_Preferenciais_Circulacao")),
                "qtot": inteiro(d.get("Quantidade_Total_Acoes_Circulacao")),
            }
            # free float 0% em companhia listada é declaração vazia, não fato:
            # a holding entrega o formulário com os campos zerados. Não publica.
            if flt["tot"] is not None and flt["qtot"]:
                reg["float"] = flt
            reg["acionistas"] = {
                "pf": inteiro(d.get("Quantidade_Acionistas_PF")),
                "pj": inteiro(d.get("Quantidade_Acionistas_PJ")),
                "inst": inteiro(d.get("Quantidade_Acionistas_Investidores_Institucionais")),
            }

        c = capital.get(cnpj)
        if c:
            reg["capital"] = c

        g = topo_por_cnpj.get(cnpj)
        if g is not None and len(g):
            linhas = []
            for _, r in g.iterrows():
                nome = (r.get("Acionista") or "").strip()
                on = inteiro(r.get("Quantidade_Acao_Ordinaria_Circulacao")) or 0
                pn = inteiro(r.get("Quantidade_Acao_Preferencial_Circulacao")) or 0
                tot = inteiro(r.get("Quantidade_Total_Acoes_Circulacao")) or (on + pn)
                linhas.append({
                    "n": nome,
                    "t": (r.get("Tipo_Pessoa_Acionista") or "").strip() or None,
                    "on": on, "pn": pn, "tot": tot,
                    "ctrl": (r.get("Acionista_Controlador") or "").strip().upper() == "S",
                    "acordo": (r.get("Participante_Acordo_Acionistas") or "").strip().upper() == "S",
                    "pais": (r.get("Nacionalidade") or "").strip() or None,
                })
            som_on = sum(x["on"] for x in linhas)
            som_pn = sum(x["pn"] for x in linhas)
            som_tot = som_on + som_pn
            reg["soma"] = {"on": som_on, "pn": som_pn}
            # a conta fecha? é o que decide se sai percentual
            fecha = False
            if c and (c["on"] + c["pn"]) > 0 and som_tot > 0:
                erro = abs(som_tot - (c["on"] + c["pn"])) / (c["on"] + c["pn"])
                fecha = erro <= TOL_FECHA
                reg["erroFecha"] = round(100 * erro, 2)
            reg["fecha"] = fecha
            # ordena por participação total, deixando "Outros" e tesouraria de fora do topo
            def marcador(x):
                return x["n"].upper() in (ROTULO_OUTROS, ROTULO_TESOURARIA)
            reais = sorted([x for x in linhas if not marcador(x)], key=lambda x: -x["tot"])
            reg["tesouraria"] = next((x["tot"] for x in linhas if x["n"].upper() == ROTULO_TESOURARIA), None)
            reg["outros"] = next((x["tot"] for x in linhas if x["n"].upper() == ROTULO_OUTROS), None)
            reg["top"] = reais[:MAX_ACIONISTAS]
            if len(reais) > MAX_ACIONISTAS:
                resto = reais[MAX_ACIONISTAS:]
                reg["demais"] = {"n": len(resto),
                                 "on": sum(x["on"] for x in resto),
                                 "pn": sum(x["pn"] for x in resto),
                                 "tot": sum(x["tot"] for x in resto)}
            # grupo de controle: a soma de todos os declarados como controladores
            ctrl = [x for x in reais if x["ctrl"]]
            if ctrl:
                reg["controle"] = {"n": len(ctrl),
                                   "on": sum(x["on"] for x in ctrl),
                                   "pn": sum(x["pn"] for x in ctrl),
                                   "tot": sum(x["tot"] for x in ctrl)}

            # ---- A COMPANHIA CONTRADIZ A SI MESMA ----------------------------
            # O free float declarado e a lista de acionistas saem do MESMO
            # formulário, e em dezenas de companhias os dois não podem ser
            # verdade ao mesmo tempo. O padrão é sempre o mesmo: o campo "ações
            # em circulação" foi preenchido com o TOTAL de ações.
            #
            # Free float, na definição da CVM e do regulamento da B3, é o que
            # sobra depois de tirar as ações do CONTROLADOR, das PESSOAS A ELE
            # VINCULADAS, da ADMINISTRAÇÃO e da TESOURARIA. As três regras abaixo
            # saem dessa definição, não de opinião sobre quem é "estratégico":
            #
            #  1. float + controlador declarado > 100,5% — impossível por
            #     definição. A ARTERIS declara 100% de circulação e três
            #     controladores com 82,3% das ordinárias; a WHIRLPOOL, 100% com
            #     controlador de 53,7%; a BOMBRIL, 100% com 70,1%.
            #  2. float >= 99,5% com participantes de ACORDO DE ACIONISTAS somando
            #     >= 10% — quem assina acordo é pessoa vinculada e não conta como
            #     circulação. A SABESP declara 100% e, no mesmo arquivo, o Estado
            #     de São Paulo com 18% e a Equatorial com 15%, os dois marcados
            #     como participantes de acordo. A COPASA declara 99,7% com um
            #     acionista de 30% em acordo.
            #     O piso de 99,5% é o que separa ERRO DE PREENCHIMENTO de nuance
            #     de definição: sem ele a regra derrubava 29 empresas, entre elas
            #     LOCALIZA, NATURA, ITAUSA e ULTRAPAR, que declaram float bem
            #     abaixo de 100% e têm acordo de acionistas minoritário — ali a
            #     soma passar de 100 é discussão de quem é "pessoa vinculada",
            #     não companhia escrevendo o total no campo errado.
            #  3. float >= 99,5% com um único acionista nomeado detendo >= 25% do
            #     capital. "Praticamente tudo em circulação" e "um quarto do
            #     capital em um nome identificado" não fecham em nenhuma leitura.
            #     Pega FICA (100% com um acionista de 44,6%), VIVER (49,8%),
            #     IMC (35,5%), WESTWING (32,4%).
            #
            # O corte de 25% é deliberadamente alto: BNDESPAR na COPEL (19,8%),
            # um gestor de recursos na VIBRA (12,5%) e um fundo na AZUL (10,5%)
            # SÃO free float pela definição, e continuam publicados. A companhia
            # perde o número; a composição acionária continua saindo, porque foi
            # ela que permitiu ver o erro.
            if reg.get("float") and fecha and capital.get(cnpj):
                cap_tot = capital[cnpj]["on"] + capital[cnpj]["pn"]
                flt = reg["float"]["tot"]
                pct = lambda q: (100.0 * q / cap_tot) if cap_tot else 0.0
                motivo = None
                pct_ctrl = pct(reg["controle"]["tot"]) if reg.get("controle") else 0.0
                pct_acordo = pct(sum(x["tot"] for x in reais if x["acordo"]))
                maior = max((pct(x["tot"]) for x in reais), default=0.0)
                if flt + pct_ctrl > 100.5:
                    motivo = {"tipo": "controlador", "float": flt, "ctrl": round(pct_ctrl, 1)}
                elif flt >= 99.5 and pct_acordo >= 10.0:
                    motivo = {"tipo": "acordo", "float": flt, "acordo": round(pct_acordo, 1)}
                elif flt >= 99.5 and maior >= 25.0:
                    grande = max(reais, key=lambda x: x["tot"])
                    motivo = {"tipo": "bloco", "float": flt, "maior": round(maior, 1),
                              "quem": grande["n"]}
                if motivo:
                    reg["floatContradiz"] = motivo
                    del reg["float"]
        out[cnpj] = reg
    log(f"ANO {ano}: {len(out)} empresas · "
        f"{sum(1 for r in out.values() if 'float' in r)} com free float · "
        f"{sum(1 for r in out.values() if r.get('fecha'))} com composição que fecha")
    return out


def main():
    por_cnpj = {}
    contagem = {}
    # do ano mais ANTIGO para o mais NOVO, para o recente sobrescrever
    for ano in sorted(ANOS):
        dados = coleta_ano(ano)
        contagem[str(ano)] = len(dados)
        por_cnpj.update(dados)
    if len(por_cnpj) < 300:
        # entregar meia base seria pior que não entregar: a tela mostraria
        # "sem composição acionária" para empresa que tem, e ninguém perceberia
        log(f"ABORTA: só {len(por_cnpj)} empresas — esperado 600+")
        sys.exit(1)

    com_float = sum(1 for r in por_cnpj.values() if "float" in r)
    contradiz = sum(1 for r in por_cnpj.values() if "floatContradiz" in r)
    com_comp = sum(1 for r in por_cnpj.values() if r.get("top"))
    com_pct = sum(1 for r in por_cnpj.values() if r.get("fecha"))
    saida = {
        "updatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fonte": "CVM · Formulário de Referência (FRE), arquivos distribuicao_capital, "
                 "posicao_acionaria e capital_social",
        "nota": "O percentual de cada acionista é recalculado como quantidade ÷ capital social. "
                "Os percentuais do próprio arquivo não servem: são relativos ao agrupamento do "
                "acionista (a União aparece com 100% das ON da Petrobras, quando detém 50,3%). "
                "Só sai percentual quando a soma dos acionistas de topo bate com o capital "
                "social dentro de 2%.",
        "anos": contagem,
        "resumo": {"empresas": len(por_cnpj), "comFloat": com_float,
                   "comComposicao": com_comp, "comPercentual": com_pct,
                   "floatContraditorio": contradiz},
        "porCnpj": por_cnpj,
    }
    OUT_FILE.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"OK {OUT_FILE} ({OUT_FILE.stat().st_size/1024:.0f} KB) · {len(por_cnpj)} empresas · "
        f"{com_float} com free float · {com_comp} com composição · {com_pct} com percentual · "
        f"{contradiz} com free float suprimido por contradizer a própria composição acionária")


if __name__ == "__main__":
    main()
