#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Série ANUAL longa das empresas listadas, direto das DFPs da CVM (2010 em diante).

Por que existe: o `process.py` monta os últimos ~10 trimestres, o que responde
"como foi o trimestre" mas não responde "esta empresa já deu prejuízo?", "qual o
CAGR de 10 anos?", "este múltiplo está caro para o padrão dela?". Tudo isso
precisa de série longa, e a CVM publica de graça: medido em 10/09/2026, o
`dfp_cia_aberta_2010.zip` tem 8,9 MB e o mesmo layout de colunas do de 2025
(CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;
ORDEM_EXERC;DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA),
com 372 empresas trazendo receita, EBIT e lucro do período.

O que sai: `data/hist.json`, colunar e compacto, lido pela página SOB DEMANDA
(não entra no HTML embutido). Um ano por arquivo DFP, sempre a coluna
ORDEM_EXERC = "ÚLTIMO" — ou seja, o número COMO FOI REPORTADO naquele exercício.
Não usamos "PENÚLTIMO" (o reapresentado) de propósito: misturar as duas colunas
faria o mesmo ano ter dois valores diferentes dependendo de qual arquivo leu.

Contas usadas (todas verificadas no DFP 2025 con: cobertura em 438 empresas,
salvo indicação): DRE 3.01 receita · 3.02 custo · 3.03 resultado bruto ·
3.04.01 despesas com vendas · 3.04.02 despesas gerais e administrativas ·
3.05 EBIT · 3.06.01 receitas financeiras · 3.06.02 despesas financeiras ·
3.07 resultado antes dos tributos · 3.08 IR/CSLL · 3.11 (ou 3.09/3.13) lucro do
período · 3.11.01 atribuído à controladora · 3.99.01.01/.02 lucro por ação (ON/PN,
nível 4 — o nível 3 vem zerado em 427 de 441 empresas — e em R$/ação, sem escala).
BPA 1 ativo · 1.01 circulante · 1.02 não circulante · 1.01.01 caixa ·
1.01.02 aplicações · 1.01.03 contas a receber · 1.01.04 estoques ·
1.02.03 imobilizado · 1.02.04 intangível. BPP 2.01 passivo circulante ·
2.02 não circulante · 2.01.04 + 2.02.01 empréstimos e financiamentos ·
2.03 patrimônio líquido · 2.03.09 participação de não controladores.
DFC_MI 6.01 caixa das operações (425) · 6.02 investimento · 6.03 financiamento ·
capex por descrição nas contas 6.02.XX. DMPL 5.04.06 dividendos e
5.04.07 juros sobre capital próprio, coluna "Patrimônio Líquido" (438).

Sobre os proventos do DMPL: são os DECLARADOS no exercício, extraídos da
demonstração auditada — não são o "DY dos últimos 12 meses" do mercado. Medido
em 10/09/2026 contra o DY do Fundamentus (114 empresas com provento e valor de
mercado): erro relativo mediano de 16%, metade dentro de 20%. A divergência é de
JANELA (exercício fechado × 12 meses móveis), não de fonte. Por isso o painel
rotula "dividendos + JCP declarados no exercício de AAAA (DMPL/CVM)" e nunca
chama isso de dividend yield.
"""
import datetime as dt
import io
import json
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).parent
DATA = BASE / "data"
TMP = DATA / "cvm_hist"
OUT_FILE = DATA / "hist.json"
for p in (DATA, TMP):
    p.mkdir(exist_ok=True)

ANO_INICIAL = 2010
HOJE = dt.date.today()
# o DFP de um ano só existe depois do fim do exercício; o ano corrente nunca tem
ANO_FINAL = HOJE.year - 1
UA = {"User-Agent": "Mozilla/5.0 (painel-b3; uso educacional/interno; contato via repo)"}
S = requests.Session()
S.headers.update(UA)
URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip"
# só o que usamos: sem isso o zip de um ano descompacta ~250 MB (DMPL_ind, parecer, DVA…)
INTERNOS = ("DRE_con", "DRE_ind", "BPA_con", "BPA_ind", "BPP_con", "BPP_ind",
            "DFC_MI_con", "DFC_MI_ind", "DMPL_con", "DMPL_ind")


def log(*a):
    print("[hist]", *a, file=sys.stderr)


def sacc(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s))
                   if unicodedata.category(c) != "Mn").lower()


def norm_cnpj(s):
    return re.sub(r"\D", "", str(s or ""))


# ---------------------------------------------------------------- universo
def universo():
    """Mesmo universo do process.py: listadas em bolsa com CNPJ e código CVM."""
    b3 = json.loads((DATA / "b3_companies.json").read_text(encoding="utf-8"))
    EXCL_SECTORS = {"Carga Inicial", "Setor Inicial"}
    EXCL_MKT = {"BALCAO NAO ORG.", "OUTROS", "SOMA"}
    u = {}
    for c in b3["companies"]:
        ind = c.get("ind") or ""
        partes = [p.strip() for p in ind.split("/")]
        if len(partes) != 3 or partes[0] in EXCL_SECTORS:
            continue
        if (c.get("mkt") or "").strip() in EXCL_MKT:
            continue
        cnpj = norm_cnpj(c.get("cnpj"))
        if not cnpj or not c.get("codeCVM"):
            continue
        u[str(int(c["codeCVM"]))] = {"cnpj": cnpj, "root": c["issuer"],
                                     "name": c.get("trad") or c.get("name")}
    return u


# ---------------------------------------------------------------- download
def baixa(ano):
    """Extrai só os CSVs que usamos. Devolve True se o ano ficou disponível."""
    alvo = TMP / f"dfp_cia_aberta_DRE_con_{ano}.csv"
    if alvo.exists():
        return True
    try:
        r = S.get(URL.format(ano=ano), timeout=300)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        n = 0
        for nome in z.namelist():
            if any(k in nome for k in INTERNOS):
                z.extract(nome, TMP)
                n += 1
        log(f"{ano}: {len(r.content)/1e6:.1f} MB, {n} arquivos")
        return n > 0
    except Exception as e:
        log(f"{ano}: FALHOU {e!r}")
        return False


USECOLS = ["CD_CVM", "VERSAO", "ESCALA_MOEDA", "ORDEM_EXERC", "DT_INI_EXERC",
           "DT_FIM_EXERC", "CD_CONTA", "DS_CONTA", "VL_CONTA"]


def le(ano, tipo, fluxo, coluna_df=False):
    """Carrega um CSV do ano já filtrado por ORDEM_EXERC=ÚLTIMO e última versão."""
    p = TMP / f"dfp_cia_aberta_{tipo}_{ano}.csv"
    if not p.exists():
        return None
    cols = list(USECOLS)
    if not fluxo:
        cols.remove("DT_INI_EXERC")
    if coluna_df:
        cols.append("COLUNA_DF")
    try:
        df = pd.read_csv(p, sep=";", encoding="latin1", dtype=str, usecols=cols)
    except Exception as e:
        log(f"{ano} {tipo}: erro de leitura {e!r}")
        return None
    df = df[df["ORDEM_EXERC"].str.upper().str.startswith("ÚLT")]
    if df.empty:
        return None
    df["CD"] = pd.to_numeric(df["CD_CVM"], errors="coerce").fillna(0).astype(int).astype(str)
    df["V"] = pd.to_numeric(df["VERSAO"], errors="coerce").fillna(1)
    df = df[df["V"] == df.groupby("CD")["V"].transform("max")]
    esc = df["ESCALA_MOEDA"].str.upper().map({"MIL": 1000.0, "UNIDADE": 1.0}).fillna(1.0)
    df["VLR"] = pd.to_numeric(df["VL_CONTA"], errors="coerce")   # cru, sem escala
    df["VL"] = df["VLR"] * esc
    return df


def par(ano, tipo, fluxo, coluna_df=False):
    """(consolidado, individual) — a empresa que não consolida cai no individual."""
    return (le(ano, tipo + "_con", fluxo, coluna_df),
            le(ano, tipo + "_ind", fluxo, coluna_df))


def mi(v):
    return None if v is None or pd.isna(v) else round(float(v) / 1e6, 1)


# ---------------------------------------------------------------- extratores
LUCRO_RE = re.compile(r"lucro|preju", re.I)
PERIODO_RE = re.compile(r"per[ií]odo|exerc[ií]cio", re.I)
DA_RE = re.compile(r"deprecia|amortiza|exaust", re.I)
# capex: as contas 6.02.XX não têm descrição padronizada (medido: 288 variantes
# em "Aquisição de imobilizado"), então é preciso casar pelo texto. Só nível 3,
# para não somar o pai e o filho da mesma rubrica.
CAPEX_RE = re.compile(
    r"(aquisi|compra|adi[cç]|desembolso|aplica|investiment|adquir).{0,40}"
    r"(imobiliz|intang|ativo fixo)|(imobiliz|intang).{0,30}(aquisi|compra|adi[cç]|adquir)", re.I)


def anual(df, cd_cvm, fluxo=True):
    """Linhas de UMA empresa, exercício fechado (01-01 a 12-31)."""
    if df is None:
        return None
    s = df[df["CD"] == cd_cvm]
    if s.empty:
        return None
    fim = s["DT_FIM_EXERC"].astype(str)
    ok = fim.str[5:] == "12-31"
    if fluxo:
        ini = s["DT_INI_EXERC"].astype(str)
        ok = ok & (ini.str[5:] == "01-01")
    s = s[ok]
    return None if s.empty else s


def dre_ano(s):
    """Devolve o dicionário de linhas da DRE de um exercício."""
    d = {}
    if s is None:
        return d
    ni_cd = nic_cd = ""
    for _, r in s.iterrows():
        cd, v = r["CD_CONTA"], r["VL"]
        if pd.isna(v):
            continue
        ds = str(r["DS_CONTA"])
        dsa = sacc(ds)
        if cd == "3.01":
            d["rev"] = v
        elif cd == "3.02":
            d["custo"] = v
        elif cd == "3.03":
            d["lucroBruto"] = v
        elif cd == "3.04.01":
            d["despVendas"] = v
        elif cd == "3.04.02":
            d["despAdm"] = v
        elif cd == "3.05":
            d["ebit"] = v
        elif cd == "3.06.01":
            d["recFin"] = v
        elif cd == "3.06.02":
            d["despFin"] = v
        elif cd == "3.07":
            d["ebt"] = v
        elif cd == "3.08":
            d["ir"] = v
        # Lucro por ação: o valor REAL fica no nível 4, por classe (3.99.01.01 "ON",
        # 3.99.01.02 "PN"/"PNA"). Medido no DFP 2025 con: 3.99.01 existe em 438
        # empresas mas vem ZERO em 427 delas — é linha de cabeçalho. E o campo é
        # R$ por ação, então usa VLR (sem a escala MIL do arquivo).
        elif cd.startswith("3.99.01.") and not pd.isna(r["VLR"]) and r["VLR"] != 0:
            classe = sacc(ds).strip()
            if classe == "on":
                d["lpaOn"] = float(r["VLR"])
            elif classe.startswith("pn"):
                # empresa com PNA e PNB: fica a de maior código (a última listada)
                d["lpaPn"] = float(r["VLR"])
        elif re.match(r"^3\.\d{2}$", cd) and LUCRO_RE.search(ds) and PERIODO_RE.search(ds) \
                and "atribu" not in dsa:
            # mesma regra do process.py: entre 3.09/3.11/3.13 vale o de maior código
            if cd >= ni_cd:
                d["ni"], ni_cd = v, cd
        elif re.match(r"^3\.\d{2}\.\d{2}$", cd) and "controladora" in dsa \
                and "nao controladores" not in dsa:
            if cd >= nic_cd:
                d["nic"], nic_cd = v, cd
    return d


def bal_ano(sa, sp):
    d = {}
    pl_cd = ""
    # "caixa" soma 1.01.01 (caixa e equivalentes) + 1.01.02 (aplicações financeiras),
    # exatamente como o process.py faz no trimestral — sem isso a dívida líquida da
    # série anual sairia diferente da do painel para a mesma empresa.
    SOMA = {"1.01.01": "caixa", "1.01.02": "caixa"}
    DIRETO = {"1": "ativo", "1.01": "atCirc", "1.02": "atNCirc",
              "1.01.03": "receb", "1.01.04": "estoq",
              "1.02.03": "imob", "1.02.04": "intang"}
    for _, r in (sa if sa is not None else pd.DataFrame()).iterrows():
        cd, v = r["CD_CONTA"], r["VL"]
        if pd.isna(v):
            continue
        if cd in SOMA:
            k = SOMA[cd]
            d[k] = d.get(k, 0.0) + v
        elif cd in DIRETO:
            d[DIRETO[cd]] = v
    for _, r in (sp if sp is not None else pd.DataFrame()).iterrows():
        cd, v = r["CD_CONTA"], r["VL"]
        if pd.isna(v):
            continue
        ds = sacc(r["DS_CONTA"])
        if cd == "2.01":
            d["pasCirc"] = v
        elif cd == "2.02":
            d["pasNCirc"] = v
        elif cd in ("2.01.04", "2.02.01") and "emprestimo" in ds:
            d["div"] = d.get("div", 0.0) + v
        elif re.match(r"^2\.\d{2}$", cd) and "patrimonio liquido" in ds:
            if cd >= pl_cd:
                d["pl"], pl_cd = v, cd
        elif re.match(r"^2\.\d{2}\.\d{2}$", cd) and "nao controladores" in ds:
            d["minor"] = v
    return d


def dfc_ano(s):
    d = {}
    capex = None
    if s is None:
        return d
    for _, r in s.iterrows():
        cd, v = r["CD_CONTA"], r["VL"]
        if pd.isna(v):
            continue
        ds = str(r["DS_CONTA"])
        if cd == "6.01":
            d["fco"] = v
        elif cd == "6.02":
            d["fci"] = v
        elif cd == "6.03":
            d["fcf"] = v
        elif cd.startswith("6.01.") and DA_RE.search(ds):
            d["da"] = d.get("da", 0.0) + v
        elif re.match(r"^6\.02\.\d{2}$", cd) and CAPEX_RE.search(ds) and v < 0:
            capex = (capex or 0.0) + abs(v)
    if capex is not None:
        d["capex"] = capex
    return d


def prov_ano(s):
    """Dividendos e JCP declarados no exercício (DMPL, coluna Patrimônio Líquido)."""
    if s is None or "COLUNA_DF" not in s.columns:
        return {}
    s = s[s["COLUNA_DF"].astype(str).str.strip() == "Patrimônio Líquido"]
    d = {}
    for _, r in s.iterrows():
        cd, v = r["CD_CONTA"], r["VL"]
        if pd.isna(v):
            continue
        ds = str(r["DS_CONTA"])
        if cd == "5.04.06" and re.match(r"^\s*dividend", ds, re.I):
            d["div"] = d.get("div", 0.0) + abs(v)
        elif cd == "5.04.07" and re.search(r"juros sobre", ds, re.I):
            d["jcp"] = d.get("jcp", 0.0) + abs(v)
    return d


# campos gravados por ano (ordem fixa: o JSON é colunar)
CAMPOS = ["rev", "custo", "lucroBruto", "despVendas", "despAdm", "ebit", "ebitda",
          "recFin", "despFin", "ebt", "ir", "ni", "nic", "lpaOn", "lpaPn",
          "ativo", "atCirc", "atNCirc", "caixa", "receb", "estoq", "imob", "intang",
          "pasCirc", "pasNCirc", "divB", "divL", "pl",
          "fco", "fci", "fcf", "capex", "fcl", "div", "jcp"]
# lpa é R$ por ação (não R$ milhões); os demais são R$ milhões
NAO_MI = {"lpaOn", "lpaPn"}


def main():
    uni = universo()
    log(f"universo: {len(uni)} empresas")
    anos = list(range(ANO_INICIAL, ANO_FINAL + 1))
    disp = [a for a in anos if baixa(a)]
    if len(disp) < 5:
        log(f"apenas {len(disp)} anos disponíveis — abortando sem gravar")
        sys.exit(1)
    log(f"anos disponíveis: {disp[0]}–{disp[-1]} ({len(disp)})")

    # cvm -> campo -> {ano: valor}
    dados = {k: {c: {} for c in CAMPOS} for k in uni}
    cobertura = {}

    for ano in disp:
        dre_c, dre_i = par(ano, "DRE", True)
        bpa_c, bpa_i = par(ano, "BPA", False)
        bpp_c, bpp_i = par(ano, "BPP", False)
        dfc_c, dfc_i = par(ano, "DFC_MI", True)
        dmp_c, dmp_i = par(ano, "DMPL", True, coluna_df=True)
        tem_con = set(dre_c["CD"].unique()) if dre_c is not None else set()
        n = 0
        for cv in uni:
            con = cv in tem_con
            pick = lambda c, i: c if con else i
            sd = anual(pick(dre_c, dre_i), cv, True)
            sa = anual(pick(bpa_c, bpa_i), cv, False)
            sp = anual(pick(bpp_c, bpp_i), cv, False)
            sf = anual(pick(dfc_c, dfc_i), cv, True)
            sm = anual(pick(dmp_c, dmp_i), cv, True)
            d = dre_ano(sd)
            b = bal_ano(sa, sp)
            f = dfc_ano(sf)
            pv = prov_ano(sm)
            if not d and not b and not f:
                continue
            n += 1
            # PL atribuído à controladora (padrão de mercado), como no process.py
            pl = b.get("pl")
            if pl is not None and b.get("minor") is not None:
                pl = pl - b["minor"]
            caixa = b.get("caixa")
            divb = b.get("div")
            ebitda = None
            if d.get("ebit") is not None and f.get("da") is not None:
                ebitda = d["ebit"] + f["da"]
            fcl = None
            if f.get("fco") is not None and f.get("capex") is not None:
                fcl = f["fco"] - f["capex"]
            linha = {
                "rev": d.get("rev"), "custo": d.get("custo"), "lucroBruto": d.get("lucroBruto"),
                "despVendas": d.get("despVendas"), "despAdm": d.get("despAdm"),
                "ebit": d.get("ebit"), "ebitda": ebitda,
                "recFin": d.get("recFin"), "despFin": d.get("despFin"),
                "ebt": d.get("ebt"), "ir": d.get("ir"),
                "ni": d.get("nic") if d.get("nic") not in (None, 0) else d.get("ni"),
                "nic": d.get("nic"), "lpaOn": d.get("lpaOn"), "lpaPn": d.get("lpaPn"),
                "ativo": b.get("ativo"), "atCirc": b.get("atCirc"), "atNCirc": b.get("atNCirc"),
                "caixa": caixa, "receb": b.get("receb"), "estoq": b.get("estoq"),
                "imob": b.get("imob"), "intang": b.get("intang"),
                "pasCirc": b.get("pasCirc"), "pasNCirc": b.get("pasNCirc"),
                "divB": divb,
                "divL": (divb - (caixa or 0)) if divb is not None else None,
                "pl": pl,
                "fco": f.get("fco"), "fci": f.get("fci"), "fcf": f.get("fcf"),
                "capex": f.get("capex"), "fcl": fcl,
                "div": pv.get("div"), "jcp": pv.get("jcp"),
            }
            for k, v in linha.items():
                if v is None:
                    continue
                dados[cv][k][ano] = round(float(v), 2) if k in NAO_MI else mi(v)
        cobertura[ano] = n
        log(f"{ano}: {n} empresas com dado")

    # ---- saída colunar: {"h": {cvm: {campo: [valores por ano, null onde falta]}}}
    h = {}
    for cv, campos in dados.items():
        obj = {}
        for k in CAMPOS:
            serie = campos[k]
            if not serie:
                continue
            obj[k] = [serie.get(a) for a in disp]
        if obj:
            h[cv] = obj
    if not h:
        log("nenhuma empresa com série — abortando sem gravar")
        sys.exit(1)

    snap = {
        "updatedAt": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "anos": disp,
        "campos": CAMPOS,
        "fonte": "CVM Dados Abertos — DFP (exercício fechado, coluna ÚLTIMO)",
        "nota": ("Valores em R$ milhões, exceto lpa (R$ por ação). Números como "
                 "reportados em cada exercício, sem reapresentação. div e jcp são "
                 "dividendos e juros sobre capital próprio DECLARADOS no exercício "
                 "(DMPL), não o dividend yield de 12 meses do mercado."),
        "cobertura": cobertura,
        "h": h,
    }
    OUT_FILE.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    log(f"OK {OUT_FILE} ({OUT_FILE.stat().st_size/1024:.0f} KB) · {len(h)} empresas · "
        f"{len(disp)} anos")

    # prova rápida no log: quem tem série completa de receita e lucro
    comp = sum(1 for o in h.values()
               if o.get("rev") and all(v is not None for v in o["rev"]))
    log(f"com receita em TODOS os {len(disp)} anos: {comp}")
    nunca = sum(1 for o in h.values()
                if o.get("ni") and len([v for v in o["ni"] if v is not None]) >= 10
                and all(v > 0 for v in o["ni"] if v is not None))
    log(f"com 10+ anos de lucro e nenhum prejuízo: {nunca}")


if __name__ == "__main__":
    main()
