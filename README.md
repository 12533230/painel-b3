# Painel B3 · Insignia Partners

Painel interativo das empresas listadas na B3 (classificação setorial oficial) com
resultados trimestrais, demonstrações conta a conta, indicadores fundamentalistas,
composição acionária e free float, documentos entregues à CVM, agenda de
resultados, comparação setorial, mapa de calor, ETFs da B3, bolsa americana, visão
macro do Brasil (Boletim Focus, moedas, cripto, agenda de juros) e notícias — com
cotações quase ao vivo. Um único HTML autocontido, que abre offline e roda como
aplicativo.

**Endereços:** `12533230.github.io/painel-b3/` (GitHub Pages, o que o APK carrega) ·
`painel-b3-delta.vercel.app` · versão pública sem marca em `/p/`.

## A regra que rege o projeto

**Denominador que não sustenta a conta não gera número — gera ausência explicada.**
Um número errado num deck custa mais que um dado faltando. Por isso o painel
não publica:

- ROE com patrimônio líquido abaixo de R$ 20 mi, ou que virou de negativo para
  positivo dentro da janela (o resultado criou o patrimônio em vez de render sobre ele);
- dív. líq./EBITDA com EBITDA negativo ou abaixo de 2% da receita;
- margem com receita negativa ou abaixo de R$ 10 mi;
- acumulado de 12 meses sem quatro trimestres **consecutivos**;
- trimestre em que a aritmética da própria entrega da empresa não fecha
  (acumulado ≠ acumulado anterior + trimestre), nem T4 derivado por subtração que
  saia negativo ou acima de 1,5× os nove meses anteriores;
- indicador de banco e seguradora que não se aplica (EBITDA, dívida, ROIC);
- free float que a companhia contradiz no MESMO formulário — declarar 100% de
  ações em circulação e, ao lado, um controlador com 82% das ordinárias (Arteris),
  um participante de acordo de acionistas com 33% (Sabesp) ou um único acionista
  identificado com 45% (Fica). São 19 das 313 empresas com declaração; as outras
  294 saem com o número;
- percentual de acionista quando a soma dos declarados não bate com o capital
  social: aí saem as quantidades, que são o dado primário do formulário.

Cada indicador tem fórmula, fonte e regra de ausência no botão **?** ao lado do
rótulo — o mesmo texto no tile, na tabela e no modal ⓘ.

## Como funciona

Sete robôs no GitHub Actions, cada um com sua cadência e seu próprio critério de
falha. Nenhum deles pode ficar verde sem entregar.

| workflow | quando | o que faz |
|---|---|---|
| `update.yml` | 3 horários/dia, todos os dias | painel completo: CVM → `process.py` → HTML interno e público |
| `quotes.yml` | 4 gatilhos em pregão, ciclo de 5 min | cotações da B3 e dos EUA no branch `quotes` |
| `noticias.yml` | a cada 2 h, todos os dias | notícias por empresa e manchetes no branch `news` |
| `extra.yml` | diário após o fechamento | índices, proventos, preço longo, série anual, composição acionária e documentos da CVM no branch `extra` |
| `vigia.yml` | 2×/hora | mede a idade do que está **publicado** e redispara o robô parado |
| `sonda.yml` | semanal + manual | testa cada fonte a partir do runner e publica o log no branch `sonda` |
| `autoteste.yml` | manual | compila todos os `.py` e roda uma amostra real; log no branch `autoteste` |

O agendamento do GitHub é *best effort* e descarta execuções — medido neste repo:
o cron horário do vigia entregou ~5 das 24 execuções/dia, e o gatilho de abertura
do pregão não saiu em dois dias seguidos. Por isso **todo robô tem mais de um
gatilho, ciclo interno em vez de muitos gatilhos, e um vigia que mede o dado
publicado em vez do agendamento**.

### Pipeline

1. `collect.py` — CVM (ITR/DFP), Fundamentus, Ibovespa, BCB (SGS e Focus), moedas,
   cripto, fóruns e manchetes. Exige os cinco ZIPs da CVM; o carimbo de hora só
   avança quando alguma fonte respondeu.
2. `collect_quotes.py` · `collect_candles.py` — cotações e candles (Yahoo).
3. `collect_indices.py` — índices da B3 por papel (1 requisição, 469 tickers).
4. `collect_proventos.py` — histórico de proventos por papel (B3).
5. `collect_precos.py` — fechamento mensal de 10 anos (retornos e múltiplo histórico).
6. `collect_hist.py` — série anual da DFP desde 2010.
7. `collect_fre.py` — composição acionária e free float, do Formulário de
   Referência. O percentual de cada acionista é recalculado sobre o capital social:
   os percentuais do próprio arquivo da CVM são relativos ao agrupamento do
   acionista, e ali a União Federal aparece com 100% das ordinárias da Petrobras
   quando detém 50,3%.
8. `collect_ipe.py` — fatos relevantes, comunicados ao mercado, avisos aos
   acionistas e o calendário oficial de eventos corporativos, com link para o PDF
   no sistema da CVM. O conjunto é reescrito pela CVM uma vez por semana, aos
   domingos, e a tela diz de quando é o documento mais recente.
9. `process.py` — consolida tudo por empresa, aplica as guardas e emite
   `painel_data.json`. Também deriva a agenda: não existe calendário de
   resultados como dado aberto (a B3 não tem rota e a CVM não tem o conjunto), e a
   estimativa é a data em que a companhia entregou o mesmo trimestre um ano antes
   — erro mediano de 1 dia, 77% dentro de 3 dias, 93% dentro de 7, medido em 625
   empresas pareadas. Sai sempre rotulada como estimativa, ao lado do calendário
   oficial da companhia quando ela publicou um.
10. `build_html.py` / `build_public.py` — injetam os dados no template.

## Camadas ao vivo no navegador (sem chave)

B3 (ações, ETFs, Ibovespa, IFIX) a cada 60 s direto na API pública da bolsa
(~15 min de defasagem) · arquivo do robô relido a cada 60 s · câmbio e cripto a
cada 60 s · Selic, CDI, IPCA e Focus a cada 5 min. Chaves opcionais do usuário
(Finnhub, brapi) ficam só no navegador.

Nenhuma das fontes novas (B3 listada, B3 índices, Yahoo chart, FRE da CVM) tem
CORS — todas passam obrigatoriamente pelo pipeline. A tela nunca sugere consulta
ao vivo onde não há.

## Fontes

CVM Dados Abertos (ITR/DFP/DFC/DMPL, FRE e IPE) · B3 (classificação setorial,
índices, proventos, cotações) · Yahoo Finance · Banco Central (SGS e Focus) ·
Fundamentus · AwesomeAPI · CoinGecko · Google News e Reddit · opcionais Finnhub e
brapi.

## Aviso

Uso informativo e educacional; não é recomendação de investimento. Os dados vêm
das fontes públicas citadas e podem conter atrasos ou erros; confira sempre os
documentos oficiais — cada empresa tem link direto para a CVM, e cada trimestre
tem link para o ITR/DFP daquele período.
