#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coletor server-side do Painel B3 (roda no GitHub Actions, com internet aberta).
Baixa: CVM (ITR/DFP), Fundamentus, Ibovespa (B3), BCB (SGS + Focus),
moedas (AwesomeAPI), cripto (CoinGecko), notícias (Reddit + Google News RSS).
Toda fonte é tolerante a falha: se cair, mantém o último valor comitado.
"""
import datetime as dt
import json, re, sys, io, zipfile, unicodedata
from pathlib import Path
import requests
from lxml import html as lxml_html, etree

BASE = Path(__file__).parent
DATA = BASE / "data"
CVM = DATA / "cvm"
OUT = BASE / "out"
for p in (DATA, CVM, OUT):
    p.mkdir(exist_ok=True)

HOJE = dt.date.today()
YCUR = HOJE.year
UA = {"User-Agent": "Mozilla/5.0 (painel-b3; uso educacional/interno; contato via repo)"}
S = requests.Session(); S.headers.update(UA)

def log(*a): print("[collect]", *a, file=sys.stderr)

def get(url, timeout=90, **kw):
    r = S.get(url, timeout=timeout, **kw)
    r.raise_for_status()
    return r

def prev_snapshot():
    p = OUT / "macro_snapshot.json"
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: pass
    p = DATA / "macro_snapshot_prev.json"
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: pass
    return {}

PREV = prev_snapshot()

# ---------------------------------------------------------------- 1. CVM
def baixa_cvm():
    anos_itr = [YCUR - 2, YCUR - 1, YCUR]
    anos_dfp = [YCUR - 2, YCUR - 1]
    urls = [f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{y}.zip" for y in anos_itr] + \
           [f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{y}.zip" for y in anos_dfp]
    ok = 0
    for u in urls:
        nome = u.rsplit("/", 1)[1]
        try:
            r = get(u, timeout=300)
            zipfile.ZipFile(io.BytesIO(r.content)).extractall(CVM)
            ok += 1
            log("CVM ok:", nome, f"{len(r.content)/1e6:.0f}MB")
        except Exception as e:
            log("CVM FALHOU:", nome, repr(e))
    # limpa arquivos que não usamos
    for f in CVM.glob("*"):
        if re.search(r"_(DRA|DMPL|parecer|DFC_MD)_", f.name):
            f.unlink(missing_ok=True)
    return ok >= 4  # precisa ao menos dos principais

# ---------------------------------------------------------------- 2. Fundamentus
FUND_COLS = ["Papel","Cotação","P/L","P/VP","PSR","Div.Yield","P/Ativo","P/Cap.Giro","P/EBIT",
             "P/Ativ Circ.Liq","EV/EBIT","EV/EBITDA","Mrg Bruta","Mrg Ebit","Mrg. Líq.",
             "Liq. Corr.","ROIC","ROE","Liq.2meses","Patrim. Líq","Dív.Líq/ Patrim.","Cresc. Rec.5a"]
def baixa_fundamentus():
    try:
        r = get("https://www.fundamentus.com.br/resultado.php")
        r.encoding = "latin-1"
        doc = lxml_html.fromstring(r.text)
        rows = doc.xpath('//table[@id="resultado"]/tbody/tr')
        if len(rows) < 300:
            raise RuntimeError(f"tabela pequena demais: {len(rows)} linhas")
        linhas = ["\t".join(FUND_COLS)]
        for tr in rows:
            tds = ["".join(td.itertext()).strip() for td in tr.xpath("./td")]
            if len(tds) == len(FUND_COLS):
                linhas.append("\t".join(tds))
        for old in DATA.glob("fundamentus_*.tsv"):
            old.unlink()
        f = DATA / f"fundamentus_{HOJE:%Y%m%d}.tsv"
        f.write_text("\n".join(linhas), encoding="utf-8")
        log("Fundamentus ok:", len(linhas) - 1, "tickers")
        return True
    except Exception as e:
        log("Fundamentus FALHOU:", repr(e))
        return False

# ---------------------------------------------------------------- 3. macro core
def j(url, timeout=30):
    return get(url, timeout=timeout).json()

def macro_core():
    core = (PREV.get("core") or {}).copy()
    def sgs(sid):
        v = j(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{sid}/dados/ultimos/1?formato=json")
        return v[0] if v else None
    for chave, sid in [("selic", 432), ("ipca12", 13522), ("cdi", 4389), ("dolarPtax", 1)]:
        try:
            v = sgs(sid)
            if v: core[chave] = v
        except Exception as e: log("SGS", sid, "falhou:", repr(e))
    try:
        dmin = (HOJE - dt.timedelta(days=12)).isoformat()
        filtro = requests.utils.quote(f"Data gt '{dmin}' and (Indicador eq 'IPCA' or Indicador eq 'Selic' "
                                      f"or Indicador eq 'PIB Total' or Indicador eq 'Câmbio' or Indicador eq 'IGP-M')")
        fo = j("https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais"
               f"?%24format=json&%24select=Indicador,Data,DataReferencia,Mediana&%24filter={filtro}"
               "&%24orderby=Data%20desc&%24top=400")
        seen, rows = set(), []
        for x in fo.get("value", []):
            k = (x["Indicador"], x["DataReferencia"])
            if k not in seen:
                seen.add(k)
                rows.append({"i": x["Indicador"], "ref": x["DataReferencia"], "med": x["Mediana"], "d": x["Data"]})
        if rows:
            rows.sort(key=lambda r: (r["i"], str(r["ref"])))
            core["focus"] = rows
    except Exception as e: log("Focus falhou:", repr(e))
    try:
        fx = j("https://economia.awesomeapi.com.br/json/last/USD-BRL,EUR-BRL,GBP-BRL,JPY-BRL,CNY-BRL,ARS-BRL,BTC-BRL")
        core["fx"] = {k: {"bid": float(v["bid"]), "pct": float(v["pctChange"]), "ts": v["create_date"], "name": v["name"]}
                      for k, v in fx.items()}
    except Exception as e: log("AwesomeAPI falhou:", repr(e))
    try:
        core["cripto"] = j("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum"
                           "&vs_currencies=usd,brl&include_24hr_change=true")
    except Exception as e: log("CoinGecko falhou:", repr(e))
    core["coletadoEm"] = dt.datetime.utcnow().isoformat() + "Z"
    return core

def ibov():
    try:
        d = j("https://cotacao.b3.com.br/mds/api/v1/DailyFluctuationHistory/IBOV", timeout=30)
        q = d["TradgFlr"]["scty"]["lstQtn"]
        last = q[-1]
        return {"date": d["TradgFlr"]["date"], "hora": last["dtTm"],
                "pontos": float(last["closPric"]), "varDia": round(float(last["prcFlcn"]), 2)}
    except Exception as e:
        log("IBOV (B3) falhou:", repr(e))
        return PREV.get("ibov")

# ---------------------------------------------------------------- 4. notícias
NEWSDOM = re.compile(r"globo\.com|infomoney|valor|exame\.|estadao|folha\.|uol\.com|cnnbrasil|moneytimes|"
                     r"braziljournal|neofeed|reuters|bloomberg|investing\.com|seudinheiro|gazetadopovo|"
                     r"poder360|metropoles|oglobo|bbc\.com|suno\.|einvestidor", re.I)
def reddit_news():
    all_posts = []
    for sub in ("investimentos", "economia", "farialimabets"):
        try:
            r = j(f"https://www.reddit.com/r/{sub}/top.json?t=week&limit=25&raw_json=1")
            for c in r["data"]["children"]:
                d = c["data"]
                all_posts.append({
                    "t": (d.get("title") or "")[:160], "sub": sub, "sc": d.get("score", 0),
                    "nc": d.get("num_comments", 0),
                    "u": d.get("url_overridden_by_dest") if (d.get("url_overridden_by_dest") and not d.get("is_self"))
                         else "https://www.reddit.com" + d.get("permalink", ""),
                    "dom": d.get("domain", ""), "self": bool(d.get("is_self")), "utc": d.get("created_utc"),
                })
        except Exception as e:
            log("Reddit", sub, "falhou:", repr(e))
    if not all_posts:
        return PREV.get("reddit") or {"news": [], "disc": []}
    news = sorted([p for p in all_posts if NEWSDOM.search(p["dom"] or "")], key=lambda x: -x["nc"])[:12]
    disc = sorted([p for p in all_posts if not NEWSDOM.search(p["dom"] or "")
                   and (p["self"] or p["sub"] != "farialimabets")], key=lambda x: -x["nc"])[:8]
    for p in disc:
        p["u"] = p["u"] if p["u"].startswith("https://www.reddit.com") else p["u"]
    return {"news": news, "disc": disc}

def gnews():
    try:
        r = get("https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=pt-BR&gl=BR&ceid=BR:pt-419", timeout=30)
        root = etree.fromstring(r.content)
        out = []
        for it in root.iter("item"):
            t = (it.findtext("title") or "").strip()
            t = re.sub(r" - [^-]+$", "", t)[:120]
            src = it.findtext("source") or ""
            d = (it.findtext("pubDate") or "")[5:16]
            if t: out.append({"t": t, "src": src, "d": d})
            if len(out) >= 12: break
        return out or PREV.get("manchetes") or []
    except Exception as e:
        log("Google News falhou:", repr(e))
        return PREV.get("manchetes") or []

# ---------------------------------------------------------------- 5. agenda
def agenda():
    p = DATA / "agenda.json"
    base = json.loads(p.read_text(encoding="utf-8")) if p.exists() else (PREV.get("agenda") or [])
    return [a for a in base if a.get("fim", a.get("dt", "")) >= HOJE.isoformat()]

# ---------------------------------------------------------------- 6. setores B3 (renova a cada ~45 dias)
def talvez_refresh_b3():
    p = DATA / "b3_companies.json"
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
        idade = (dt.datetime.utcnow() - dt.datetime.fromisoformat(meta.get("fetchedAt", "2000-01-01T00:00:00").replace("Z", ""))).days
    except Exception:
        idade = 999
    if idade < 45:
        log(f"b3_companies.json com {idade} dias — sem refresh")
        return
    try:
        import refresh_b3
        refresh_b3.main()
    except Exception as e:
        log("refresh B3 falhou (mantendo arquivo atual):", repr(e))

# ---------------------------------------------------------------- main
if __name__ == "__main__":
    ok_f = baixa_fundamentus()
    ok_c = baixa_cvm()
    talvez_refresh_b3()
    snap = {
        "snapshotEm": HOJE.isoformat(),
        "core": macro_core(),
        "ibov": ibov(),
        "agenda": agenda(),
        "reddit": reddit_news(),
        "manchetes": gnews(),
        "fontesAgenda": "BCB (Copom), Federal Reserve (FOMC), BCE, IBGE",
    }
    (OUT / "macro_snapshot.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    (DATA / "macro_snapshot_prev.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    log("macro_snapshot.json ok")
    if not (ok_f and ok_c):
        log("ATENÇÃO: fonte essencial falhou (fundamentus ou CVM). Abortando para não publicar painel incompleto.")
        sys.exit(1)
