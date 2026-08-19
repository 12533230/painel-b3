# Painel B3 · Insignia Partners

Painel interativo das empresas listadas na B3 (classificação setorial oficial) com
resultados trimestrais, indicadores fundamentalistas, ETFs da B3, bolsa americana
(índices, ETFs e ações), visão macro do Brasil (Boletim Focus, moedas, cripto,
agenda de juros) e notícias da semana — com cotações quase ao vivo.

**Painel ao vivo:** https://SEU_USUARIO.github.io/painel-b3/ *(GitHub Pages, atualizado
automaticamente em dias úteis ~6h10 de Brasília)*

## Como funciona

Dois workflows do GitHub Actions:

**`update.yml` (diário, dias úteis ~6h10 Brasília)** — o painel completo:

1. `collect.py` — baixa demonstrações da CVM (ITR/DFP), a tabela do Fundamentus,
   Ibovespa (B3), indicadores e Boletim Focus (APIs do Banco Central), moedas
   (AwesomeAPI), cripto (CoinGecko) e notícias (Reddit + Google News). Toda fonte tem
   fallback: se falhar, mantém o último dado publicado. A classificação setorial da B3
   se renova sozinha a cada ~45 dias (`refresh_b3.py`).
2. `collect_quotes.py` — snapshot de cotações (Yahoo Finance) embutido no HTML.
3. `process.py` — consolida os balanços por empresa e calcula os indicadores
   (EBITDA, margens, ROE, ROIC, dívida líquida/EBITDA, valor de mercado etc.).
4. `build_html.py` — injeta os dados no template e publica `docs/index.html`.

**`quotes.yml` (a cada 15 min em horário de pregão)** — roda `collect_quotes.py`
(cotações da B3 completa, ETFs e EUA via Yahoo Finance) e publica `data/quotes.json`
no branch `quotes` (force-push de 1 commit, para não inflar o histórico). O painel
relê esse arquivo a cada 60 s via raw.githubusercontent.com.

## Camadas de "ao vivo" no navegador

Com a página aberta e internet (nada disso exige chave):

- **B3 — ações, ETFs, Ibovespa e IFIX**: consultadas a cada 60 s direto na API
  pública da própria B3 (CORS aberto; feed com ~15 min de defasagem do pregão).
- **EUA + lista completa da B3**: `quotes.json` do robô, relido a cada 60 s.
- **Câmbio e cripto**: AwesomeAPI e CoinGecko a cada 60 s.
- **Selic/CDI/IPCA e Focus**: BCB a cada 5 min.

Chaves gratuitas **opcionais** (botão "⚙ Ao vivo" no painel; ficam no localStorage
do navegador): **Finnhub** deixa ações/ETFs dos EUA em tempo real no navegador;
**brapi** busca as cotações da B3 em lote (1 chamada).

As listas padrão de ETFs da B3 e de índices/ETFs/ações dos EUA ficam em
`data/watchlists.json` — edite e faça commit para mudar o que o robô coleta.
No navegador, "➕ acompanhar outro" adiciona tickers só para você (localStorage).

## Fontes

CVM Dados Abertos (ITR/DFP) · B3 (classificação setorial, Ibovespa/IFIX e cotações
quase ao vivo) · Yahoo Finance (cotações EUA e B3 via robô) · Banco Central
(SGS e Expectativas/Focus) · Fundamentus (múltiplos de mercado) · AwesomeAPI (câmbio) ·
CoinGecko (cripto) · IBGE, BCB, Fed e BCE (calendários) · Reddit e Google News
(repercussão) · opcionais: Finnhub e brapi (chaves gratuitas do usuário).

## Aviso

Uso informativo e educacional; não é recomendação de investimento. Os dados vêm de
fontes públicas citadas acima e podem conter atrasos ou erros; confira sempre os
documentos oficiais (links por empresa dentro do painel).
