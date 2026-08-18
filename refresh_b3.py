#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconstrói data/b3_companies.json pela API pública de empresas listadas da B3."""
import base64, datetime as dt, json, sys, time
from pathlib import Path
import requests

BASE = Path(__file__).parent
DATA = BASE / "data"
API = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall"
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (painel-b3)"})

def p64(o): return base64.b64encode(json.dumps(o).encode()).decode()
def call(metodo, params):
    r = S.get(f"{API}/{metodo}/{p64(params)}", timeout=30)
    r.raise_for_status()
    return r.json()

def main():
    tax = call("GetIndustryClassification", {"language": "pt-br"})
    todos = []
    for pg in range(1, 40):
        r = call("GetInitialCompanies", {"language": "pt-br", "pageNumber": pg, "pageSize": 120, "company": ""})
        rs = r.get("results") or []
        todos += rs
        if pg >= (r.get("page", {}).get("totalPages") or 1):
            break
        time.sleep(0.1)
    eq = [c for c in todos if c.get("status") == "A" and not c.get("typeBDR")
          and c.get("segment") and not c["segment"].lower().startswith("não classificado")]
    print(f"[refresh_b3] {len(todos)} registros, {len(eq)} empresas a detalhar", file=sys.stderr)
    det, falhas = [], 0
    for i, c in enumerate(eq):
        try:
            d = call("GetDetail", {"codeCVM": c["codeCVM"], "language": "pt-br"})
            det.append({"codeCVM": c["codeCVM"], "issuer": c["issuingCompany"], "name": d.get("companyName"),
                        "trad": d.get("tradingName"), "cnpj": d.get("cnpj"), "ind": d.get("industryClassification"),
                        "codes": [x.get("code") for x in (d.get("otherCodes") or [])], "site": (d.get("website") or "").strip(),
                        "seg": c.get("segment"), "mkt": d.get("market"), "cat": d.get("describleCategoryBVMF"),
                        "hasQ": d.get("hasQuotation")})
        except Exception:
            falhas += 1
        time.sleep(0.12)
    if len(det) < 350:
        raise RuntimeError(f"poucas empresas detalhadas ({len(det)}); mantendo arquivo anterior")
    out = {"fetchedAt": dt.datetime.utcnow().isoformat() + "Z", "taxonomy": tax, "companies": det}
    (DATA / "b3_companies.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"[refresh_b3] ok: {len(det)} empresas ({falhas} falhas)", file=sys.stderr)

if __name__ == "__main__":
    main()
