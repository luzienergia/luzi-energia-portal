# Arquivo — páginas desativadas em 25/08/2026

O portal do cliente e o painel admin saíram do ar quando a gestão migrou para o
painel dentro do Claude (artefato `luzi-painel-gestao`) e o cliente passou a
receber o PDF completo pelo WhatsApp.

Nada foi apagado — os arquivos estão aqui caso um dia precise consultar ou voltar.

- `admin.html`        — painel administrativo antigo
- `cliente.html`      — portal do cliente (login e histórico de faturas)
- `servidor_admin.py` — servidor local que rodava o admin
- `atualizar_site.py` — script que alimentava o admin/cliente

O `sincronizar_portal.py` continua gerando `portal/data.json`, que hoje só serve
de backup: o site novo (`index.html`) é institucional e não lê dados.
