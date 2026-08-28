#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline Painel B3 — consolida classificação setorial (B3), demonstrações (CVM) e
indicadores de mercado (Fundamentus) num único JSON para o painel.
Reprodutível: mesmas entradas => mesmo painel. Pensado para rodar também em CI.
"""
import datetime as _dt
import json, re, sys, unicodedata
from pathlib import Path
import pandas as pd

BASE = Path(__file__).parent
DATA = BASE / "data"
CVM = DATA / "cvm"
OUT = BASE / "out"
OUT.mkdir(exist_ok=True)

# anos dinâmicos: sempre os 3 últimos de ITR e 2 de DFP (vira o ano sozinho)
_HOJE = _dt.date.today()
YCUR = _HOJE.year
YEARS_ITR = [YCUR - 2, YCUR - 1, YCUR]
YEARS_DFP = [YCUR - 2, YCUR - 1]
_QCUR = (_HOJE.month - 1) // 3 + 1
QUARTERS = [(y, q) for y in YEARS_ITR for q in (1, 2, 3, 4) if (y, q) <= (YCUR, _QCUR)]

def norm_cnpj(s):
    return re.sub(r"\D", "", str(s or ""))

# ---------------------------------------------------------------- universo B3
b3 = json.loads((DATA / "b3_companies.json").read_text(encoding="utf-8"))
TICKER_RE = re.compile(r"^[A-Z0-9]{4}(3|4|5|6|11)$")
EXCL_SECTORS = {"Carga Inicial", "Setor Inicial"}
EXCL_MKT = {"BALCAO NAO ORG.", "OUTROS", "SOMA"}

universe = {}
for c in b3["companies"]:
    ind = c.get("ind") or ""
    parts = [p.strip() for p in ind.split("/")]
    if len(parts) != 3:
        continue
    setor, subsetor, segmento = parts
    if setor in EXCL_SECTORS:
        continue
    mkt = (c.get("mkt") or "").strip()
    if mkt in EXCL_MKT:
        continue
    # todas as listadas em bolsa entram, mesmo sem ticker negociado/cotação
    tickers = sorted({t for t in (c.get("codes") or []) if TICKER_RE.match(t)})
    cnpj = norm_cnpj(c.get("cnpj"))
    if not cnpj or not c.get("codeCVM"):
        continue
    universe[cnpj] = {
        "cvm": str(int(c["codeCVM"])), "root": c["issuer"], "name": c.get("trad") or c.get("name"),
        "fullName": c.get("name"), "cnpj": cnpj, "setor": setor, "subsetor": subsetor,
        "segmento": segmento, "listagem": mkt, "site": (c.get("site") or "").strip(),
        "tickers": tickers,
    }
print(f"universo: {len(universe)} empresas", file=sys.stderr)
CNPJS = set(universe)

# ------------------------------------------------------------- fundamentus
def br_num(s):
    s = str(s).strip().replace("%", "")
    if not s or s in ("-", ""):
        return None
    neg = s.startswith("-")
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None

fund = {}
FUND_FILE = sorted(DATA.glob("fundamentus_*.tsv"))[-1]  # mais recente
FUND_DATE = re.search(r"(\d{4})(\d{2})(\d{2})", FUND_FILE.name)
UPDATED = "-".join(FUND_DATE.groups()) if FUND_DATE else "2026-08-18"
flines = FUND_FILE.read_text(encoding="utf-8").splitlines()
fhead = flines[0].split("\t")
for ln in flines[1:]:
    v = ln.split("\t")
    if len(v) != len(fhead):
        continue
    r = dict(zip(fhead, v))
    t = r["Papel"].strip()
    fund[t] = {
        "cot": br_num(r["Cotação"]), "pl": br_num(r["P/L"]), "pvp": br_num(r["P/VP"]),
        "psr": br_num(r["PSR"]), "dy": br_num(r["Div.Yield"]), "evebit": br_num(r["EV/EBIT"]),
        "evebitda": br_num(r["EV/EBITDA"]), "mrgebit": br_num(r["Mrg Ebit"]), "mrgliq": br_num(r["Mrg. Líq."]),
        "roic": br_num(r["ROIC"]), "roe": br_num(r["ROE"]), "liq2m": br_num(r["Liq.2meses"]),
        "dlpl": br_num(r["Dív.Líq/ Patrim."]), "cresc5a": br_num(r["Cresc. Rec.5a"]),
        "liqcorr": br_num(r["Liq. Corr."]),
    }
print(f"fundamentus: {len(fund)} tickers", file=sys.stderr)

# ------------------------------------------------------------- CVM loaders
USECOLS = ["CNPJ_CIA", "CD_CVM", "DT_REFER", "VERSAO", "GRUPO_DFP", "ESCALA_MOEDA", "ORDEM_EXERC",
           "DT_FIM_EXERC", "CD_CONTA", "DS_CONTA", "VL_CONTA"]
USECOLS_FLOW = USECOLS + ["DT_INI_EXERC"]
CVM_CODES = {m["cvm"] for m in universe.values()}
CVM_BY_CODE = {m["cvm"]: cnpj for cnpj, m in universe.items()}

def load_csv(name, flow):
    p = CVM / name
    if not p.exists():
        return None
    df = pd.read_csv(p, sep=";", encoding="latin1", dtype=str,
                     usecols=(USECOLS_FLOW if flow else USECOLS))
    df = df[df["ORDEM_EXERC"].str.upper().str.startswith("ÚLT")]
    df["CD"] = pd.to_numeric(df["CD_CVM"], errors="coerce").fillna(0).astype(int).astype(str)
    df = df[df["CD"].isin(CVM_CODES)]
    df["CNPJ"] = df["CD"].map(CVM_BY_CODE)
    df["VL"] = pd.to_numeric(df["VL_CONTA"], errors="coerce")
    scale = df["ESCALA_MOEDA"].str.upper().map({"MIL": 1000.0, "UNIDADE": 1.0}).fillna(1.0)
    df["VL"] = df["VL"] * scale  # reais
    df["VERSAO"] = pd.to_numeric(df["VERSAO"], errors="coerce").fillna(1)
    # mantém última versão por (empresa, data de referência)
    vmax = df.groupby(["CNPJ", "DT_REFER"])["VERSAO"].transform("max")
    df = df[df["VERSAO"] == vmax]
    return df

def load_all(kind, flow=False):
    """kind ex.: 'DRE', 'BPA' -> concat ITR+DFP anos, con e ind separados."""
    frames_con, frames_ind = [], []
    for y in YEARS_ITR:
        d = load_csv(f"itr_cia_aberta_{kind}_con_{y}.csv", flow); d is not None and frames_con.append(d.assign(SRC=f"ITR{y}"))
        d = load_csv(f"itr_cia_aberta_{kind}_ind_{y}.csv", flow); d is not None and frames_ind.append(d.assign(SRC=f"ITR{y}"))
    for y in YEARS_DFP:
        d = load_csv(f"dfp_cia_aberta_{kind}_con_{y}.csv", flow); d is not None and frames_con.append(d.assign(SRC=f"DFP{y}"))
        d = load_csv(f"dfp_cia_aberta_{kind}_ind_{y}.csv", flow); d is not None and frames_ind.append(d.assign(SRC=f"DFP{y}"))
    con = pd.concat(frames_con, ignore_index=True) if frames_con else pd.DataFrame()
    ind = pd.concat(frames_ind, ignore_index=True) if frames_ind else pd.DataFrame()
    return con, ind

# ------------------------------------------------- documentos (link por entrega)
# os CSVs "master" (itr_cia_aberta_YYYY.csv) trazem ID_DOC/LINK_DOC por entrega
doc_frames = []
for y in YEARS_ITR:
    p = CVM / f"itr_cia_aberta_{y}.csv"
    if p.exists():
        doc_frames.append(pd.read_csv(p, sep=";", encoding="latin1", dtype=str))
for y in YEARS_DFP:
    p = CVM / f"dfp_cia_aberta_{y}.csv"
    if p.exists():
        doc_frames.append(pd.read_csv(p, sep=";", encoding="latin1", dtype=str))
DOCID = {}
if doc_frames:
    docs = pd.concat(doc_frames, ignore_index=True)
    docs["CNPJ"] = docs["CNPJ_CIA"].map(norm_cnpj)
    docs["V"] = pd.to_numeric(docs["VERSAO"], errors="coerce").fillna(1)
    docs = docs.sort_values("V").groupby(["CNPJ", "DT_REFER"]).tail(1)
    for _, r in docs.iterrows():
        did = str(r.get("ID_DOC") or "").strip()
        if did:
            DOCID[(r["CNPJ"], r["DT_REFER"])] = did
print(f"documentos com link: {len(DOCID)}", file=sys.stderr)

print("carregando DRE...", file=sys.stderr)
dre_con, dre_ind = load_all("DRE", flow=True)
print("carregando BPA/BPP...", file=sys.stderr)
bpa_con, bpa_ind = load_all("BPA")
bpp_con, bpp_ind = load_all("BPP")
print("carregando DFC_MI...", file=sys.stderr)
dfc_con, dfc_ind = load_all("DFC_MI", flow=True)

HAS_CON = set(dre_con["CNPJ"].unique())

def pick(df_con, df_ind, cnpj):
    return df_con if cnpj in HAS_CON else df_ind

# ------------------------------------------------------------- extração DRE
LUCRO_RE = re.compile(r"lucro|preju", re.I)
PERIODO_RE = re.compile(r"per[ií]odo", re.I)

def strip_acc(s):
    return "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn").lower()

QSTART = {1: "01-01", 2: "04-01", 3: "07-01", 4: "10-01"}
QEND = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}

def dre_values(sub):
    """sub: linhas DRE de UMA empresa. Retorna {(y,q):{'rev','ebit','ni'}} + ytd p/ derivação."""
    out = {}
    ytd = {}
    if sub.empty:
        return out, ytd
    # net income: maior conta topo (3.N) cujo DS bate lucro/prejuízo do período
    for _, r in sub.iterrows():
        cd, ds = r["CD_CONTA"], str(r["DS_CONTA"])
        fim, ini = r["DT_FIM_EXERC"], r["DT_INI_EXERC"]
        try:
            y = int(fim[:4]); m = int(fim[5:7])
        except Exception:
            continue
        q = {3: 1, 6: 2, 9: 3, 12: 4}.get(m)
        if q is None:
            continue
        is_q = ini and ini[5:] == QSTART[q]
        is_ytd = ini and ini[5:] == "01-01"
        key = None
        dsa = strip_acc(ds)
        if cd == "3.01":
            key = "rev"
        elif cd == "3.05":
            key = "ebit"
        elif re.match(r"^3\.\d{2}$", cd) and LUCRO_RE.search(ds) and PERIODO_RE.search(ds) and "atribu" not in dsa:
            key = "ni"
        elif re.match(r"^3\.\d{2}\.\d{2}$", cd) and "controladora" in dsa and "nao controladores" not in dsa:
            key = "nic"  # lucro atribuído a sócios da controladora (padrão de mercado)
        if key is None:
            continue
        v = r["VL"]
        if pd.isna(v):
            continue
        if is_q:
            out.setdefault((y, q), {})
            if key in ("ni", "nic"):
                prev = out[(y, q)].get("_%scd" % key, "")
                if cd >= prev:
                    out[(y, q)][key] = v; out[(y, q)]["_%scd" % key] = cd
            else:
                out[(y, q)][key] = v
        if is_ytd:
            ytd.setdefault((y, q), {})
            if key in ("ni", "nic"):
                prev = ytd[(y, q)].get("_%scd" % key, "")
                if cd >= prev:
                    ytd[(y, q)][key] = v; ytd[(y, q)]["_%scd" % key] = cd
            else:
                ytd[(y, q)][key] = v
    # deriva trimestres faltantes por diferença de acumulados
    for (y, q) in list(ytd.keys()):
        for key in ("rev", "ebit", "ni", "nic"):
            if key in ytd.get((y, q), {}) and key not in out.get((y, q), {}):
                if q == 1:
                    out.setdefault((y, q), {})[key] = ytd[(y, q)][key]
                elif (y, q - 1) in ytd and key in ytd[(y, q - 1)]:
                    out.setdefault((y, q), {})[key] = ytd[(y, q)][key] - ytd[(y, q - 1)][key]
    return {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in out.items()}, ytd

# T4 = DFP(ano) - ITR T3 acumulado
def add_t4(out, ytd, sub_dfp):
    for _, r in sub_dfp.iterrows():
        cd, ds = r["CD_CONTA"], str(r["DS_CONTA"])
        fim = r["DT_FIM_EXERC"]
        ini = r.get("DT_INI_EXERC")
        try:
            y = int(fim[:4])
        except Exception:
            continue
        if not (fim[5:] == "12-31" and ini and ini[5:] == "01-01"):
            continue
        key = None
        dsa = strip_acc(ds)
        if cd == "3.01":
            key = "rev"
        elif cd == "3.05":
            key = "ebit"
        elif re.match(r"^3\.\d{2}$", cd) and LUCRO_RE.search(ds) and PERIODO_RE.search(ds) and "atribu" not in dsa:
            key = "ni"
        elif re.match(r"^3\.\d{2}\.\d{2}$", cd) and "controladora" in dsa and "nao controladores" not in dsa:
            key = "nic"
        if key is None or pd.isna(r["VL"]):
            continue
        y3 = ytd.get((y, 3), {})
        if key in y3:
            out.setdefault((y, 4), {})[key] = r["VL"] - y3[key]
    return out

# ------------------------------------------------------------- D&A (DFC MI)
DA_RE = re.compile(r"deprecia|amortiza|exaust", re.I)

def da_values(sub):
    """YTD de depreciação/amortização por (y,q); só contas 6.01.*"""
    ytd = {}
    for _, r in sub.iterrows():
        cd = r["CD_CONTA"]
        if not cd.startswith("6.01."):
            continue
        if not DA_RE.search(str(r["DS_CONTA"])):
            continue
        fim, ini = r["DT_FIM_EXERC"], r["DT_INI_EXERC"]
        try:
            y = int(fim[:4]); m = int(fim[5:7])
        except Exception:
            continue
        q = {3: 1, 6: 2, 9: 3, 12: 4}.get(m)
        if q is None or not ini or ini[5:] != "01-01" or pd.isna(r["VL"]):
            continue
        ytd[(y, q)] = ytd.get((y, q), 0.0) + r["VL"]
    quarters = {}
    for (y, q), v in ytd.items():
        if q == 1:
            quarters[(y, q)] = v
        elif (y, q - 1) in ytd:
            quarters[(y, q)] = v - ytd[(y, q - 1)]
    return quarters

# ------------------------------------------------------------- balanço
def bal_values(sub_a, sub_p):
    """último balanço disponível + série de PL por trimestre."""
    res = {}
    for _, r in sub_a.iterrows():
        fim = r["DT_FIM_EXERC"]; cd = r["CD_CONTA"]
        if pd.isna(r["VL"]):
            continue
        d = res.setdefault(fim, {})
        if cd == "1":
            d["ativo"] = r["VL"]
        elif cd == "1.01.01":
            d["caixa"] = d.get("caixa", 0.0) + r["VL"]
        elif cd == "1.01.02":
            d["aplic"] = d.get("aplic", 0.0) + r["VL"]
    for _, r in sub_p.iterrows():
        fim = r["DT_FIM_EXERC"]; cd = r["CD_CONTA"]; ds = strip_acc(str(r["DS_CONTA"]))
        if pd.isna(r["VL"]):
            continue
        d = res.setdefault(fim, {})
        if re.match(r"^2\.\d{2}$", cd) and "patrimonio liquido" in ds:
            # pega a conta de PL de maior código (con: 'PL Consolidado'; bancos usam 2.07/2.08)
            if cd >= d.get("_plcd", ""):
                d["pl"] = r["VL"]; d["_plcd"] = cd
        elif re.match(r"^2\.\d{2}\.\d{2}$", cd) and "nao controladores" in ds:
            d["minor"] = r["VL"]  # participação de minoritários dentro do PL
        elif cd in ("2.01.04", "2.02.01") and "emprestimo" in ds:
            d["div"] = d.get("div", 0.0) + r["VL"]
    return res

# ------------------------------------------------------------- capital/mktcap
cap_frames = []
for y in sorted(set(YEARS_ITR + YEARS_DFP), reverse=True):
    for pref in ("itr", "dfp"):
        p = CVM / f"{pref}_cia_aberta_composicao_capital_{y}.csv"
        if p.exists():
            cf = pd.read_csv(p, sep=";", encoding="latin1", dtype=str)
            cap_frames.append(cf)
if not cap_frames:
    sys.exit("composição de capital ausente — abortando (mktcap ficaria todo vazio)")
cap = pd.concat(cap_frames, ignore_index=True)
CNPJ8 = {c[:8]: c for c in CNPJS}
cap["CNPJ"] = cap["CNPJ_CIA"].map(norm_cnpj).str[:8].map(CNPJ8)
cap = cap[cap["CNPJ"].notna()]
for col in ["QT_ACAO_ORDIN_CAP_INTEGR", "QT_ACAO_PREF_CAP_INTEGR", "QT_ACAO_ORDIN_TESOURO", "QT_ACAO_PREF_TESOURO"]:
    cap[col] = pd.to_numeric(cap[col], errors="coerce").fillna(0)
cap = cap.sort_values("DT_REFER").groupby("CNPJ").tail(1)
shares = {r["CNPJ"]: {"on": r["QT_ACAO_ORDIN_CAP_INTEGR"] - r["QT_ACAO_ORDIN_TESOURO"],
                      "pn": r["QT_ACAO_PREF_CAP_INTEGR"] - r["QT_ACAO_PREF_TESOURO"],
                      "ref": r["DT_REFER"]}
          for _, r in cap.iterrows()}

# ------------------------------------------------------------- montagem
FIN_SUBSETORES = {"Intermediários Financeiros", "Previdência e Seguros", "Securitizadoras de Recebíveis"}

def tk_fund(meta):
    return [fund.get(t) for t in meta["tickers"] if fund.get(t)]

def fmt_mi(v):  # reais -> R$ milhões, 1 casa
    return None if v is None else round(v / 1e6, 1)

def build_company(cnpj, meta):
    dre = pick(dre_con, dre_ind, cnpj)
    sub = dre[dre["CNPJ"] == cnpj]
    sub_itr = sub[sub["SRC"].str.startswith("ITR")]
    sub_dfp = sub[sub["SRC"].str.startswith("DFP")]
    out, ytd = dre_values(sub_itr)
    out = add_t4(out, ytd, sub_dfp)

    dfc = pick(dfc_con, dfc_ind, cnpj)
    subd = dfc[dfc["CNPJ"] == cnpj]
    da_q = da_values(subd[subd["SRC"].str.startswith("ITR")])

    # D&A anual (DFP) para derivar T4
    da_year = {}
    dd = subd[subd["SRC"].str.startswith("DFP")]
    for _, r in dd.iterrows():
        cd = r["CD_CONTA"]
        if not cd.startswith("6.01.") or not DA_RE.search(str(r["DS_CONTA"])):
            continue
        fim, ini = r["DT_FIM_EXERC"], r["DT_INI_EXERC"]
        if fim[5:] == "12-31" and ini and ini[5:] == "01-01" and not pd.isna(r["VL"]):
            y = int(fim[:4])
            da_year[y] = da_year.get(y, 0.0) + r["VL"]
    # ytd T3 do ITR p/ diff
    da_ytd_itr = {}
    di = subd[subd["SRC"].str.startswith("ITR")]
    for _, r in di.iterrows():
        cd = r["CD_CONTA"]
        if not cd.startswith("6.01.") or not DA_RE.search(str(r["DS_CONTA"])):
            continue
        fim, ini = r["DT_FIM_EXERC"], r["DT_INI_EXERC"]
        if ini and ini[5:] == "01-01" and fim[5:] == "09-30" and not pd.isna(r["VL"]):
            y = int(fim[:4])
            da_ytd_itr[y] = da_ytd_itr.get(y, 0.0) + r["VL"]
    for y, v in da_year.items():
        if y in da_ytd_itr:
            da_q[(y, 4)] = v - da_ytd_itr[y]

    bpa = pick(bpa_con, bpa_ind, cnpj); bpp = pick(bpp_con, bpp_ind, cnpj)
    bal = bal_values(bpa[bpa["CNPJ"] == cnpj], bpp[bpp["CNPJ"] == cnpj])

    isfin = meta["subsetor"] in FIN_SUBSETORES
    qlist = []
    for (y, q) in QUARTERS:
        d = out.get((y, q), {})
        if not d:
            continue
        rev, ebit = d.get("rev"), d.get("ebit")
        # controladora primeiro; várias empresas zeram o desdobramento 3.11.01 => cai no consolidado
        nic = d.get("nic")
        ni = nic if (nic is not None and nic != 0) else d.get("ni")
        da = da_q.get((y, q))
        ebitda = (ebit + da) if (ebit is not None and da is not None and not isfin) else None
        item = {
            "p": f"{y}T{q}", "rev": fmt_mi(rev), "ebit": fmt_mi(ebit) if not isfin else None,
            "ebitda": fmt_mi(ebitda), "ni": fmt_mi(ni),
            "mgE": round(100 * ebitda / rev, 1) if (ebitda and rev) else None,
            "mgL": round(100 * ni / rev, 1) if (ni is not None and rev) else None,
        }
        doc = DOCID.get((cnpj, f"{y}-{QEND[q]}"))
        if doc:
            item["doc"] = doc  # ID do documento na CVM (ITR do tri; DFP no T4)
        qlist.append(item)
    # últimos 4 trimestres p/ 12m
    have = {c["p"]: c for c in qlist}
    keys = [f"{y}T{q}" for (y, q) in QUARTERS]
    last4 = [have[k] for k in keys if k in have][-4:]
    def s12(f):
        vals = [c[f] for c in last4 if c.get(f) is not None]
        return round(sum(vals), 1) if len(vals) == 4 else None
    rev12, ebit12, ebitda12, ni12 = s12("rev"), s12("ebit"), s12("ebitda"), s12("ni")

    # histórico de balanço por trimestre (p/ séries de ROE/ROIC/dívida no painel)
    QENDS = {"03-31", "06-30", "09-30", "12-31"}
    bhist = []
    for dtb in sorted(bal.keys()):
        if dtb[5:] not in QENDS:
            continue
        b = bal[dtb]
        plq = b.get("pl")
        if plq is not None and b.get("minor") is not None:
            plq = plq - b["minor"]
        cx = (b.get("caixa") or 0) + (b.get("aplic") or 0)
        dv = b.get("div")
        bhist.append({"dt": dtb, "pl": fmt_mi(plq),
                      "divL": fmt_mi(dv - cx) if (dv is not None and not isfin) else None})

    lastbal = None
    if bal:
        dt = max(bal.keys())
        b = bal[dt]
        caixa = (b.get("caixa") or 0) + (b.get("aplic") or 0)
        div = b.get("div")
        pl = b.get("pl")
        if pl is not None and b.get("minor") is not None:
            pl = pl - b["minor"]  # PL atribuído à controladora (padrão de mercado)
        lastbal = {
            "dt": dt, "ativo": fmt_mi(b.get("ativo")), "pl": fmt_mi(pl),
            "caixa": fmt_mi(caixa if caixa else None),
            "divB": fmt_mi(div) if not isfin else None,
            "divL": fmt_mi(div - caixa) if (div is not None and not isfin) else None,
        }
    ind = {}
    if rev12: ind["rev12"] = rev12
    if ebitda12: ind["ebitda12"] = ebitda12
    if ni12 is not None: ind["ni12"] = ni12
    if ebitda12 and rev12: ind["mgE12"] = round(100 * ebitda12 / rev12, 1)
    if ni12 is not None and rev12: ind["mgL12"] = round(100 * ni12 / rev12, 1)
    if lastbal and lastbal.get("pl"):
        if ni12 is not None: ind["roe"] = round(100 * ni12 / lastbal["pl"], 1)
        if lastbal.get("divL") is not None:
            ind["dlPl"] = round(lastbal["divL"] / lastbal["pl"], 2)
            if ebitda12: ind["dlEbitda"] = round(lastbal["divL"] / ebitda12, 2)
            if ebit12:
                invested = lastbal["pl"] + max(lastbal["divL"], 0)
                if invested: ind["roic"] = round(100 * (ebit12 * 0.66) / invested, 1)

    # market cap — composição de capital vem sem escala declarada (umas empresas
    # reportam em unidades, outras em milhares); desambiguamos contra Fundamentus.
    sh = shares.get(cnpj)
    mcap = None
    pl_reais = (lastbal["pl"] * 1e6) if (lastbal and lastbal.get("pl")) else None
    if sh:
        pon = fund.get(meta["root"] + "3", {}).get("cot")
        pn_cands = [(fund.get(meta["root"] + s, {}).get("liq2m") or 0, fund.get(meta["root"] + s, {}).get("cot"))
                    for s in ("4", "5", "6")]
        pn_cands = [(lq, ct) for lq, ct in pn_cands if ct]
        ppn = max(pn_cands)[1] if pn_cands else None
        on, pn = sh["on"], sh["pn"]
        tot = on + pn
        if tot > 0:
            if on / tot < 0.005: on = 0   # classes residuais (ex.: 1 ação PN)
            if pn / tot < 0.005: pn = 0
        ok = (on == 0 or pon is not None) and (pn == 0 or ppn is not None) and (on + pn) > 0
        if ok:
            base = (on * (pon or 0)) + (pn * (ppn or 0))
            # referência de mercado p/ escolher escala (unidades vs milhares)
            best = None
            for f in sorted([f for f in tk_fund(meta) if f], key=lambda x: -(x.get("liq2m") or 0)):
                if ni12 and ni12 > 0 and (f.get("pl") or 0) > 0:
                    best = f["pl"] * ni12 * 1e6; break
                if pl_reais and (f.get("pvp") or 0) > 0:
                    best = f["pvp"] * pl_reais; break
            for scale in (1.0, 1000.0):
                cand = base * scale
                if best:
                    if best / 3 <= cand <= best * 3:
                        mcap = cand; break
                elif scale == 1.0 and 2e8 <= cand <= 5e12:
                    mcap = cand  # sem referência: aceita só se plausível em unidades
    if mcap:
        ind["mktCap"] = fmt_mi(mcap)
        if ni12 and ni12 > 0: ind["plCalc"] = round(mcap / 1e6 / ni12, 1)
        if lastbal and lastbal.get("divL") is not None:
            ind["ev"] = round(mcap / 1e6 + lastbal["divL"], 1)  # valor da firma (EV)
            if ebitda12:
                ind["evEbitda"] = round((mcap / 1e6 + lastbal["divL"]) / ebitda12, 1)

    tk = []
    for t in meta["tickers"]:
        f = fund.get(t)
        if f and f.get("cot"):
            tk.append({"t": t, **{k: v for k, v in f.items() if v is not None}})
    links = {
        "b3": f"https://www.b3.com.br/pt_br/produtos-e-servicos/negociacao/renda-variavel/empresas-listadas.htm?codigoCvm={meta['cvm']}",
        "cvm": f"https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx?codigoCVM={meta['cvm']}",
    }
    if meta["tickers"]:
        links["fund"] = f"https://www.fundamentus.com.br/detalhes.php?papel={meta['tickers'][0]}"
    if meta["site"]:
        site = meta["site"]
        if not site.startswith("http"): site = "https://" + site
        links["ri"] = site
    return {
        **{k: meta[k] for k in ("root", "name", "fullName", "cnpj", "cvm", "setor", "subsetor", "segmento", "listagem")},
        "fin": isfin, "con": cnpj in HAS_CON,
        "tickers": tk, "q": qlist, "bal": lastbal, "bh": bhist, "ind": ind, "links": links,
    }

companies = []
for cnpj, meta in universe.items():
    try:
        companies.append(build_company(cnpj, meta))
    except Exception as e:
        print("ERRO", meta["root"], repr(e), file=sys.stderr)

# todas as listadas em bolsa entram; sem dado nenhum a linha mostra "—"
companies.sort(key=lambda c: (c["setor"], c["subsetor"], c["segmento"], c["name"] or ""))

panel = {
    "updatedAt": UPDATED,
    "b3FetchedAt": b3.get("fetchedAt"),
    "fontes": {"demonstracoes": "CVM Dados Abertos (ITR/DFP)", "setores": "B3 Classificação Setorial",
               "mercado": f"Fundamentus ({UPDATED})"},
    "companies": companies,
}
(OUT / "painel_data.json").write_text(json.dumps(panel, ensure_ascii=False), encoding="utf-8")
ncur = sum(1 for c in companies if any(x["p"].startswith(str(YCUR)) for x in c["q"]))
print(f"OK {len(companies)} empresas no painel | {ncur} com trimestre {YCUR} | JSON: {(OUT/'painel_data.json').stat().st_size/1024:.0f} KB", file=sys.stderr)
