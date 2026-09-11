#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coletor de notícias por empresa (roda no noticias.yml, a cada 2h, todos os dias).

Para cada empresa listada (data/b3_companies.json) consulta o RSS do Google News
e grava data/news.json:

  {"updatedAt": iso, "janelaDias": 30, "comNoticia": n,
   "n": {codigoCVM: [{"t": título, "src": veículo, "d": "dd/mm",
                      "iso": "AAAA-MM-DD", "u": link}, ...]}}

O painel mostrava "Notícias recentes" com matéria de 2021. As causas foram
medidas em 07/09/2026 (267 consultas ao feed, 1.415 itens) e cada uma tem um
tratamento aqui:

  1. A query não tinha filtro de recência. Sem `when:`, 90% dos 6 itens que o
     script gravava por empresa tinham mais de 30 dias (mediana 193 dias; o mais
     antigo era de 2017). Agora vai `when:30d`, e o filtro do Google se mostrou
     confiável (0 item fora da janela em 259 medidos).
  2. O feed vem por RELEVÂNCIA, não por data (só 44,9% dos pares em ordem
     cronológica; `scoring=n` não muda nada). Pegar os 6 primeiros do XML
     descartava a notícia mais nova em 21 de 30 feeds. Agora lê o feed inteiro e
     ordena aqui.
  3. A data era gravada como "dd/mm", sem ano: 16,9% dos itens do arquivo
     publicado tinham dia/mês POSTERIOR ao próprio updatedAt — matéria de um ano
     atrás parecendo da semana. O pubDate traz ano em 100% dos itens; agora vai
     a data completa.
  4. Página automática de cotação não é notícia. Os 12 filtros de título abaixo,
     mais a regra da fonte "B3", pegaram 278 de 3.840 títulos distintos na medição
     de 07/09/2026, com 1 falso positivo conhecido. Valem sobre o título CRU.
  5. Nada expirava: item herdado do arquivo anterior ficava para sempre. Agora
     item com data velha (ou sem data) sai do arquivo.
  6. ~40% das empresas não têm notícia na janela (24 de 40 na amostra tinham).
     Isso é estado normal, não falha: a empresa fica com lista vazia e o painel
     diz "nenhuma notícia nos últimos 30 dias". Ampliar a janela para 90 dias
     recuperaria 4 empresas — e 4 dos 5 itens recuperados eram lixo.

Tolerância a falha: falha de rede (None) mantém as notícias anteriores da
empresa; feed vazio é resposta legítima e sobrescreve. Se a coleta inteira
desabar, ou se a cobertura despencar (bloqueio do Google), o arquivo publicado
NÃO é sobrescrito.
"""
import datetime as dt
import json, re, sys, time, unicodedata
from collections import Counter
from email.utils import parsedate_to_datetime
from pathlib import Path
import requests
from lxml import etree

BASE = Path(__file__).parent
DATA = BASE / "data"
OUT_FILE = DATA / "news.json"
UA = {"User-Agent": "Mozilla/5.0 (painel-b3; uso educacional/interno; contato via repo)"}
RSS = "https://news.google.com/rss/search"
MAX_POR_EMPRESA = 6
JANELA_DIAS = 30          # o que a query pede ao Google (when:30d)
MAX_IDADE_DIAS = 35       # cinto de segurança: item mais velho que isso sai do arquivo
GENERICA_MIN = 10         # manchete que aparece em N empresas é notícia de mercado, não da empresa

def log(*a): print("[news]", *a, file=sys.stderr)

def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default

def semacento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")

# ---- páginas automáticas de cotação/ticker que o Google indexa como notícia ----
# Derivados de corpus real (3.840 títulos distintos em 07/09/2026): 278 capturados.
LIXO_TITULO = [
    # [^!?\n] em vez de [^.!?]: "ROMI3 - Romi S.a. - Resultados, Dividendos, Cotação"
    # escapava por causa do ponto. O (?!…) evita o único falso positivo medido:
    # "AALR3, AMBP3 e JHSF3 na agenda de resultados da semana" (lista de tickers).
    re.compile(r"^[A-Z]{4}\d{1,2}\b(?![^!?\n]{0,40}[A-Z]{4}\d{1,2})[^!?\n]{0,90}\b(cota[çc][ãa]o|resultados|indicadores)\b", re.I),
    re.compile(r"\b(cota[çc][ãa]o|cota[çc][õo]es)\s*,\s*(dividendos|indicadores|balan[çc]os|gr[áa]ficos?)", re.I),
    re.compile(r"BMFBOVESPA\s*:\s*[A-Z]{4}\d{1,2}", re.I),
    re.compile(r"^(A[çc][ãa]o\s+[A-Z]{4}\d{1,2}\s*:|[A-Z]{4}\d{1,2}\s+ETF\s+Hoje|Previs[ãa]o\s+[A-Z]{4}\d{1,2}\b|Gr[áa]ficos\s+Sazonais\b)", re.I),
    re.compile(r"(^An[áa]lise\s+t[ée]cnica\s+d[oe]|Demonstrativo\s+(Financeiro|de\s+Resultados)|Detalhamento\s+da\s+Receita|^Vis[ãa]o\s+geral\s+dos\s+fundamentos)", re.I),
    re.compile(r"(\([A-Z]{4}\d{1,2}\)\s*Pre[çc]o\s+da\s+a[çc][ãa]o|\b(Stock|ETF)\s+Price\s+and\s+Chart\b)", re.I),
    re.compile(r"^(Cota[çc][ãa]o\s+.{0,60}hoje\s*:|Cota[çc][õo]es\s+(de\s+A[çc][õo]es|em\s+Tempo\s+Real))", re.I),
    re.compile(r"^[A-Z]{4}\d{1,2}\b[^\n]{0,90}(\d+,\d+\s*%|Ibovespa)"),   # sem re.I: o ticker é maiúsculo
    # páginas de cotação do InvestNews ("Ação AGXY3.SA - Ações Agrogalaxy – AGXY3 - Cotação"):
    # 6 acertos e 0 falso positivo em 1.906 títulos do corpus medido
    re.compile(r"^A[çc][ãa]o\s+[A-Z]{4}\d{1,2}(\.SA)?\s*[-–]", re.I),
    re.compile(r"^Not[íi]cias\s+da\s+Bolsa\s+de\s+Valores", re.I),
    # "Itaú | ITUB3 | ITUB4 - Ações na bolsa" (página de ativo do Valor)
    re.compile(r"[A-Z]{4}\d{1,2}\s*\|\s*[A-Z]{4}\d{1,2}"),
    re.compile(r"A[çc][õo]es\s+na\s+bolsa\s*$", re.I),
]
def eh_lixo(titulo_cru, fonte, titulo_limpo=None):
    if any(r.search(titulo_cru) for r in LIXO_TITULO):
        return True
    # A própria B3 publica página institucional sem notícia ("IPO", "Novo Mercado").
    # Conta as palavras do título já sem o sufixo " - B3", senão o limite de 3
    # nunca era alcançado.
    if (fonte or "").strip() == "B3" and len((titulo_limpo or titulo_cru).split()) <= 3:
        return True
    return False

def norm_titulo(t):
    return re.sub(r"[^a-z0-9]+", " ", semacento(t or "").lower()).strip()

# palavras de razão social que não identificam a empresa
LIXO_RAZAO = {"s.a.", "sa", "ltda", "holding", "holdings", "participacoes", "participacao",
              "part", "cia", "companhia", "brasil", "brasileira", "brasileiro", "group",
              "grupo", "industria", "industrias", "comercio", "servicos", "empreendimentos",
              "distribuidora", "nacional", "unidas", "units", "banco"}
def termos_empresa(c):
    """Tokens que, no título, indicam que a matéria é sobre ESTA empresa."""
    t = set()
    for cod in (c.get("codes") or []):
        if cod: t.add(cod.lower())
    if c.get("issuer"): t.add(str(c["issuer"]).lower())
    for campo in ("trad", "name"):
        for w in re.split(r"[^a-z0-9]+", semacento(str(c.get(campo) or "")).lower()):
            if len(w) >= 4 and w not in LIXO_RAZAO:
                t.add(w)
    return t

# Sem fronteira de palavra, "elet" casava dentro de "eletricidade" e manchete
# alheia subia como notícia da empresa. Medido: 11 itens em 9 empresas.
def menciona(titulo, termos):
    tl = semacento(titulo).lower()
    for t in termos:
        if not t:
            continue
        if re.search(r"(?<![0-9a-z])" + re.escape(t) + r"(?![0-9a-z])", tl):
            return True
    return False

def data_iso(s):
    """'Wed, 02 Sep 2026 17:33:14 GMT' -> (date, 'AAAA-MM-DD', 'dd/mm'); None se ilegível."""
    try:
        d = parsedate_to_datetime(s)
        if d is None:
            return None
        d = d.date()
        return (d, d.isoformat(), f"{d.day:02d}/{d.month:02d}")
    except Exception:
        return None

EXCL_MKT = {"BALCAO NAO ORG.", "OUTROS", "SOMA"}
EXCL_SECTORS = {"Carga Inicial", "Setor Inicial"}

# razão social sem o entulho jurídico, para a consulta de reserva. Medido: com o
# nome curto ("ITAUUNIBANCO", tudo junto) o feed vem VAZIO; com "ITAU UNIBANCO"
# vem notícia de 6 dias. Não substitui o nome curto — em SABESP, CPFL, MILLS e
# SMART FIT o curto é bem melhor —, entra só quando o primeiro não achou nada.
RE_LEGAL = re.compile(r"\b(s\s*\.?\s*a\.?|sa|ltda|me|epp|cia|companhia|holdings?|"
                      r"participa[çc][õo]es|participa[çc][ãa]o|part\.?)\b", re.I)
def nome_alternativo(c):
    n = re.sub(r"[.,]", " ", str(c.get("name") or ""))
    n = RE_LEGAL.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip()
    n = " ".join(n.split(" ")[:5])
    curto = str(c.get("trad") or "").strip()
    if len(n) < 5 or semacento(n).lower() == semacento(curto).lower():
        return ""
    return n

def busca_rss(session, consulta):
    """XML do feed, ou None em falha de rede/parse."""
    try:
        r = session.get(RSS, params={"q": consulta, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"},
                        timeout=(5, 15))
        r.raise_for_status()
        return etree.fromstring(r.content)
    except Exception:
        return None

def fetch_news(session, empresa, hoje):
    """Lista de notícias (possivelmente vazia) no sucesso; None só em falha real."""
    nome = (empresa.get("trad") or empresa.get("name") or "").strip()
    itens = coleta(session, f'"{nome}" B3 when:{JANELA_DIAS}d', empresa, hoje)
    # O nome curto de negociação não é como a imprensa escreve. Medido: "MAGAZ
    # LUIZA" devolve 3 itens, nenhum citando a empresa; "MAGAZINE LUIZA" devolve
    # 68, com a notícia de verdade. Então quando a 1ª consulta não trouxe NADA que
    # cite a empresa (não só quando vem vazia), consulta a razão social e junta as
    # duas listas. Custa 1 request extra em ~metade das empresas.
    alt = nome_alternativo(empresa)
    if alt and (itens is None or not any(x["_men"] for x in itens)):
        time.sleep(0.35)
        it2 = coleta(session, f'"{alt}" B3 when:{JANELA_DIAS}d', empresa, hoje)
        if it2:
            itens = (itens or []) + it2
    if itens is None:
        return None
    # dedup entre as duas consultas, e a ordem final
    vistos, unicos = set(), []
    for it in itens:
        k = norm_titulo(it["t"])
        if k in vistos:
            continue
        vistos.add(k)
        unicos.append(it)
    # Quem cita a empresa primeiro, depois o mais recente: metade dos itens do
    # feed é notícia de mercado que só menciona a empresa de passagem. Duas
    # ordenações estáveis fazem isso sem chave composta.
    unicos.sort(key=lambda x: x["iso"], reverse=True)
    unicos.sort(key=lambda x: 0 if x["_men"] else 1)
    return unicos[:MAX_POR_EMPRESA]

def coleta(session, consulta, empresa, hoje):
    """Itens válidos de UMA consulta (sem ordenar nem cortar); None em falha de rede."""
    root = busca_rss(session, consulta)
    if root is None:
        return None
    termos = termos_empresa(empresa)
    itens, vistos = [], set()
    for it in root.iter("item"):                 # o feed inteiro: a ordem dele é por relevância
        cru = (it.findtext("title") or "").strip()
        u = (it.findtext("link") or "").strip()
        src = (it.findtext("source") or "").strip()
        if not cru or not u:
            continue
        # o Google News anexa " - <source>" ao título; cortar pelo próprio campo
        # acerta 100% dos casos (a regex antiga errava quando o veículo tem hífen)
        t = cru[:-(len(src) + 3)].strip() if src and cru.endswith(" - " + src) else cru
        t = t[:140]
        if not t or eh_lixo(cru, src, t):
            continue
        d = data_iso(it.findtext("pubDate"))
        if not d:
            continue                             # sem data não entra: não dá para dizer se é recente
        data, iso, ddmm = d
        idade = (hoje - data).days
        if idade > MAX_IDADE_DIAS or idade < -1:  # -1 tolera fuso; futuro além disso é erro da fonte
            continue
        k = norm_titulo(t)
        if k in vistos:
            continue
        vistos.add(k)
        itens.append({"t": t, "src": src[:60], "d": ddmm, "iso": iso, "u": u,
                      "_men": menciona(t, termos)})
    return itens

def limpa_antigos(itens, hoje):
    """Item herdado do arquivo anterior também expira — e sem data não fica."""
    out = []
    for it in itens or []:
        iso = it.get("iso")
        if not iso:
            continue          # arquivo antigo gravava só "dd/mm": sem ano, não dá para datar
        try:
            data = dt.date.fromisoformat(str(iso)[:10])
        except Exception:
            continue
        if (hoje - data).days <= MAX_IDADE_DIAS:
            out.append(it)
    return out

def main():
    # --amostra N  usa 1 empresa a cada k (determinístico) e NÃO grava o arquivo:
    # é como o autoteste.yml confere a coleta de verdade sem 4 minutos de fila.
    amostra = 0
    if "--amostra" in sys.argv:
        try: amostra = max(1, int(sys.argv[sys.argv.index("--amostra") + 1]))
        except Exception: amostra = 12
    hoje = dt.datetime.utcnow().date()
    b3 = load_json(DATA / "b3_companies.json", {})
    empresas = []
    for c in b3.get("companies") or []:
        # mesmo universo do process.py (mkt é o SEGMENTO de listagem: Novo Mercado, Nível 1…)
        parts = [p.strip() for p in (c.get("ind") or "").split("/")]
        if len(parts) != 3 or parts[0] in EXCL_SECTORS or (c.get("mkt") or "").strip() in EXCL_MKT:
            continue
        try:
            cvm = str(int(c["codeCVM"]))
        except Exception:
            continue
        if (c.get("trad") or c.get("name") or "").strip():
            empresas.append((cvm, c))
    if not empresas:
        log("nenhuma empresa no universo — abortando sem gravar")
        sys.exit(1)
    if amostra:
        empresas.sort(key=lambda x: (x[1].get("trad") or ""))
        k = max(1, len(empresas) // amostra)
        empresas = empresas[::k][:amostra]
        log(f"MODO AMOSTRA: {len(empresas)} empresas, sem gravar arquivo")

    prev = load_json(OUT_FILE, {})
    prev_n = dict(prev.get("n") or {})
    prev_com_item = sum(1 for v in prev_n.values() if v)
    n = {}
    sem_resposta = []
    falhas_seguidas = 0
    com_item = 0
    s = requests.Session(); s.headers.update(UA)
    for i, (cvm, emp) in enumerate(empresas):
        itens = fetch_news(s, emp, hoje)
        if itens is None:                        # falha real (HTTP/parse)
            falhas_seguidas += 1
            sem_resposta.append(cvm)
            # grava a chave mesmo vazia: sem isso a página não distingue
            # "sem notícia na janela" de "não consegui consultar"
            n[cvm] = limpa_antigos(prev_n.get(cvm), hoje)
            if falhas_seguidas >= 30:
                log("30 falhas de rede em sequência — abortando a coleta")
                break
        else:
            falhas_seguidas = 0
            n[cvm] = itens                       # inclusive vazio: "sem notícia na janela"
            if itens:
                com_item += 1
        if i % 100 == 0:
            log(f"{i}/{len(empresas)} ({com_item} com notícia)")
        time.sleep(0.35)                          # educado com o Google News

    # empresa que não chegou a ser consultada mantém o que havia, já expirado
    # (no modo amostra isso traria as ~340 empresas do arquivo anterior)
    if not amostra:
        for cvm, v in prev_n.items():
            if cvm not in n:
                resto = limpa_antigos(v, hoje)
                if resto:
                    n[cvm] = resto

    # manchete de mercado ("Ibovespa fecha em alta") aparece no feed de dezenas de
    # empresas: sai de quem tem notícia própria, fica em quem não tem mais nada
    cont = Counter()
    for itens in n.values():
        for it in itens:
            cont[norm_titulo(it["t"])] += 1
    genericas = 0
    if not amostra:      # com 12 empresas o limiar de 10 não significa nada
        for cvm, itens in n.items():
            # sai sempre, mesmo que a empresa fique sem nada: "Ibovespa fecha o
            # último pregão aos 166.335 pontos" na aba da Panatlântica passa por
            # notícia da empresa, e "nenhuma notícia nos últimos 30 dias" é mais
            # honesto do que isso
            mantidos = [it for it in itens if it.get("_men") or cont[norm_titulo(it["t"])] < GENERICA_MIN]
            genericas += len(itens) - len(mantidos)
            n[cvm] = mantidos
    for itens in n.values():                      # marca interna não vai para o arquivo
        for it in itens:
            it.pop("_men", None)

    com_item = sum(1 for v in n.values() if v)
    if amostra:
        log(f"{com_item} das {len(empresas)} empresas da AMOSTRA têm notícia na janela de {JANELA_DIAS}d")
    else:
        log(f"{com_item} empresas com notícia na janela de {JANELA_DIAS}d "
            f"(antes: {prev_com_item}) · {len(n)} no arquivo · {genericas} manchetes de mercado removidas"
            + (f" · {len(sem_resposta)} sem resposta da fonte" if sem_resposta else ""))
    if amostra:
        # mostra o que sairia na tela, para dar para conferir a olho no log do CI
        for cvm, itens in list(n.items())[:amostra]:
            nome = next((str(e[1].get("trad")) for e in empresas if e[0] == cvm), cvm)
            log(f"--- {nome} ({cvm}): {len(itens)} item(ns)")
            for it in itens:
                log(f"      {it['iso']} | {it['src'][:18]:<18} | {it['t'][:80]}")
        log("MODO AMOSTRA: nada gravado")
        return
    if com_item == 0:
        log("nada coletado — abortando sem gravar (o painel mantém o arquivo anterior)")
        sys.exit(1)
    # queda brusca de cobertura = bloqueio/soft-ban do Google, não notícia que acabou.
    # A primeira execução depois desta reescrita cai de propósito (o arquivo antigo
    # tinha item de qualquer idade), por isso o piso é 40% e não 80%.
    if prev_com_item >= 50 and com_item < prev_com_item * 0.4:
        log(f"cobertura caiu de {prev_com_item} para {com_item} (<40%) — "
            f"provável bloqueio; abortando sem gravar")
        sys.exit(1)

    snap = {"updatedAt": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "janelaDias": JANELA_DIAS, "maxIdadeDias": MAX_IDADE_DIAS, "comNoticia": com_item,
            "semResposta": sem_resposta, "n": n}
    OUT_FILE.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"OK {OUT_FILE} ({OUT_FILE.stat().st_size/1024:.0f} KB)")

if __name__ == "__main__":
    main()
