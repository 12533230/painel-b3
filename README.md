# Painel B3 · Insignia Partners

Painel interativo das empresas listadas na B3 (classificação setorial oficial) com
resultados trimestrais, indicadores fundamentalistas, visão macro do Brasil
(Boletim Focus, moedas, cripto, agenda de juros) e notícias da semana.

**Painel ao vivo:** https://SEU_USUARIO.github.io/painel-b3/ *(GitHub Pages, atualizado
automaticamente em dias úteis ~6h10 de Brasília)*

## Como funciona

Um workflow do GitHub Actions (`.github/workflows/update.yml`) roda em dias úteis:

1. `collect.py` — baixa demonstrações da CVM (ITR/DFP), a tabela do Fundamentus,
   Ibovespa (B3), indicadores e Boletim Focus (APIs do Banco Central), moedas
   (AwesomeAPI), cripto (CoinGecko) e notícias (Reddit + Google News). Toda fonte tem
   fallback: se falhar, mantém o último dado publicado. A classificação setorial da B3
   se renova sozinha a cada ~45 dias (`refresh_b3.py`).
2. `process.py` — consolida os balanços por empresa e calcula os indicadores
   (EBITDA, margens, ROE, ROIC, dívida líquida/EBITDA, valor de mercado etc.).
3. `build_html.py` — injeta os dados no template e publica `docs/index.html`.

O HTML é autocontido: abre offline com o último snapshot e, com internet, atualiza
ao vivo câmbio, cripto, Selic/CDI/IPCA e Focus direto no navegador (APIs públicas com CORS).

## Fontes

CVM Dados Abertos (ITR/DFP) · B3 (classificação setorial e Ibovespa) · Banco Central
(SGS e Expectativas/Focus) · Fundamentus (múltiplos de mercado) · AwesomeAPI (câmbio) ·
CoinGecko (cripto) · IBGE, BCB, Fed e BCE (calendários) · Reddit e Google News (repercussão).

## Aviso

Uso informativo e educacional; não é recomendação de investimento. Os dados vêm de
fontes públicas citadas acima e podem conter atrasos ou erros; confira sempre os
documentos oficiais (links por empresa dentro do painel).
