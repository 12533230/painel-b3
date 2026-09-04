# Publicação no Vercel

O `vercel.json` não aceita comentários (o schema do Vercel rejeita chaves extras,
inclusive `"//"`), então as decisões ficam registradas aqui.

## O que o Vercel serve

`outputDirectory: docs` — o Vercel publica a pasta `docs/` já construída. **Não há
build no Vercel**: quem gera o `docs/index.html` é o GitHub Actions
(`collect.py` → `process.py` → `build_html.py` → `build_public.py`), e cada commit
do robô dispara um deploy automático.

Com `docs/` virando a raiz do domínio, dois efeitos úteis:

- o painel interno fica em `/` (em vez de `/painel-b3/`) e o público em `/p/`
- `docs/.well-known/assetlinks.json` cai exatamente onde o Android o procura,
  o que é o que permite o app abrir em tela cheia, sem a barra do Chrome

## Cache

O HTML carrega os dados embutidos no próprio arquivo, então **não pode ficar preso
em cache** — sem `must-revalidate` a atualização diária não apareceria para quem já
visitou. Mesma coisa para o `sw.js`: um service worker em cache mantém o app numa
versão antiga. Ícones e manifest mudam raramente e ficam com cache de um dia.

## Redirects

`/painel-b3/*` → `/*` mantém funcionando os links antigos e o APK já instalado,
que aponta para `https://12533230.github.io/painel-b3/`.

## Domínio próprio

Para usar `painel.insigniapartners.com.br`, adicione o domínio em
*Project → Settings → Domains* e crie o registro DNS que o Vercel indicar.
Ao mudar de domínio, o APK precisa ser regerado apontando para o novo endereço,
e o `assetlinks.json` tem de ser servido na raiz **desse** domínio.

## GitHub Pages continua no ar

O Pages segue publicando o mesmo `docs/` em `12533230.github.io/painel-b3/`.
Manter os dois é intencional: o APK instalado aponta para o Pages e continua
funcionando, enquanto o Vercel serve o acesso por navegador.
