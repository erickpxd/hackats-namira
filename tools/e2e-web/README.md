# E2E legado do console vanilla

Este harness exercitava a interface removida de `web/` e não valida o frontend atual.
O frontend suportado está em `frontend/` e roda pelo Vite; a API Python não serve arquivos
da interface. Para validar o frontend atual, execute `npm run build` dentro de `frontend/`
e use o preview/proxy do Vite junto ao backend local.
