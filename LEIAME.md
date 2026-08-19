# Insignia Partners · Painel B3 — pipeline de atualização

Gerado em 18/08/2026 pelo Claude (Cowork), a pedido de André Mendes.
Identidade visual: paleta e tipografia do Manual de Marca Insignia + tema do
Template_Insignia_v4.pptx (Tahoma; teal #0C2A2D/#18494E, sage #638876; gráficos em
#18494E/#DCB604/#4F47AD no claro e #5BA7B6/#DCB604/#817ADB no escuro — separação
CVD validada). Logos embutidos em base64 na pasta brand/ (não remover do zip).

## O que é
`Painel_B3.html` é um painel interativo autocontido (abre em qualquer navegador,
sem internet) com as ~342 empresas listadas na B3, organizadas pela classificação
setorial oficial da B3 (Setor → Subsetor → Segmento), com:

- resultados trimestrais 2024T1–2026T2 (receita, EBIT, EBITDA, lucro, margens) — CVM (ITR/DFP);
- balanço mais recente (ativo, PL, caixa, dívida bruta/líquida) — CVM;
- indicadores 12m calculados: ROE, ROIC, dív. líq./EBITDA, dív. líq./PL, margens, valor de mercado;
- múltiplos de mercado por ticker (P/L, P/VP, EV/EBITDA, DY, ROIC, ROE…) — Fundamentus;
- links diretos por empresa: documentos oficiais na CVM, busca da central de resultados/RI, Fundamentus.

## Convenções de cálculo
- Demonstrações consolidadas quando disponíveis (senão, individuais).
- Lucro líquido = atribuído aos sócios da controladora (padrão de mercado); quando a
  empresa zera esse desdobramento no XBRL, usa-se o consolidado.
- EBITDA = EBIT (3.05) + depreciação/amortização (DFC método indireto). Não se aplica a
  bancos/seguradoras/securitizadoras.
- Dívida bruta = Empréstimos e Financiamentos (circulante + não circulante).
- Valor de mercado = ações ex-tesouraria (composição de capital CVM) × cotação por classe
  (Fundamentus), com desambiguação de escala validada contra P/L / P/VP.
- ROIC (CVM) = EBIT 12m × (1 − 34%) ÷ (PL + dívida líquida) — aproximação; o ROIC do
  Fundamentus também é exibido.

## Como atualizar (o fluxo que o Claude executa)
1. Coleta via navegador (Chrome conectado ao Claude):
   - Fundamentus: exportar a tabela de `fundamentus.com.br/resultado.php` (TSV);
   - CVM: baixar `dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_2026.zip`
     (e DFP do ano anterior quando virar o ano);
   - B3 (1x por trimestre basta): API `sistemaswebb3-listados.b3.com.br` → `b3_companies.json`.
2. Rodar `process.py` (gera `out/painel_data.json`).
3. Rodar `build_html.py` (gera `out/Painel_B3.html`).
4. Substituir o arquivo nesta pasta e atualizar o artifact "painel-b3" no Cowork.

Há uma tarefa agendada no Claude toda segunda-feira de manhã que executa esse fluxo.
Ela precisa do aplicativo Claude aberto no desktop (para acessar Chrome e esta pasta).
Você também pode pedir a qualquer momento: "atualiza o painel B3".

## Visão "Brasil & Macro" + ticker
O painel tem uma segunda visão (Brasil & Macro) e uma faixa de cotações no topo.
- AO VIVO no navegador (CORS aberto, sem chave): AwesomeAPI (moedas), CoinGecko (BTC/ETH),
  BCB SGS (Selic 432, IPCA 12m 13522, CDI 4389) e BCB Olinda (Boletim Focus). Atualiza ao abrir
  e a cada 5 min.
- SNAPSHOT semanal (renovar via Chrome na atualização): out/macro_snapshot.json, montado a partir de
  data/macro_core.json (mesmos endpoints acima, coletados navegando para api.bcb.gov.br e usando fetch),
  Ibovespa em https://cotacao.b3.com.br/mds/api/v1/DailyFluctuationHistory/IBOV (sem CORS → só snapshot),
  notícias em reddit.com (/r/investimentos, /r/economia, /r/farialimabets → top.json?t=week, ranqueadas
  por comentários; filtrar domínios de notícia) e manchetes do Google News RSS (topic BUSINESS, pt-BR).
- Agenda (Copom/FOMC/BCE/IBGE): datas oficiais de 2026 embutidas em macro_snapshot.json; renovar
  quando os calendários de 2027 saírem.

## Arquivos
- `process.py` — consolida CVM + B3 + Fundamentus e calcula os indicadores.
- `build_html.py` — injeta os dados no template e gera o HTML final.
- `painel_template.html` — o template do painel (layout/JS).
- `b3_companies.json` — classificação setorial B3 por empresa (coletada 18/08/2026).
- `painel_data.json` — último dataset consolidado.

Uso informativo; não é recomendação de investimento.

## Mobile

O layout é responsivo: em telas ≤900px a árvore de setores vira dois seletores (setor e subsetor/segmento) acima da lista; tabelas ganham rolagem horizontal com a primeira coluna fixa (`border-collapse:separate` + `position:sticky`; `overflow:visible` na tabela — `collapse`/`overflow:hidden` quebram sticky no Chromium). Em ≤760px o cabeçalho quebra em duas linhas (busca em largura total, botões só com ícone), o detalhe da empresa ocupa a tela inteira com ✕ flutuante, e a tabela de fontes do ⓘ Dados vira lista empilhada. Inputs com font-size 16px para evitar zoom automático no iOS. Testes: `node test_mobile.js` (Playwright, iPhone 390×844 + desktop 1366).
