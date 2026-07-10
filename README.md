# Movimento 7 - site com inscrições

Aplicação Flask pronta para publicação no Render, com banco PostgreSQL, formulário protegido por CSRF, painel administrativo e exportação CSV.

## Executar localmente

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Abra `http://127.0.0.1:5000`. Sem `DATABASE_URL`, a aplicação cria `instance/movimento7.db`.

## Publicar no Render

1. Suba esta pasta para um repositório GitHub.
2. No Render, escolha **New > Blueprint** e conecte o repositório.
3. O arquivo `render.yaml` criará o serviço web e o PostgreSQL.
4. Aguarde o deploy e abra a URL gerada.
5. No painel do serviço, copie ou troque `ADMIN_PASSWORD` por uma senha conhecida.
6. Acesse `/admin/entrar` para gerenciar as inscrições.

> Planos e nomes de recursos do Render podem mudar. Caso o Blueprint não ofereça plano gratuito, escolha o plano disponível e mantenha as mesmas variáveis.

## Rotas

- `/` - página principal
- `/inscricao` - formulário
- `/inscricao/recebida` - confirmação
- `/privacidade` - política de dados
- `/admin/entrar` - login administrativo
- `/admin` - painel
- `/admin/inscricoes.csv` - exportação
- `/saude` - health check

## Edição rápida

- Cores, fontes e espaçamentos: `app/static/css/style.css`, bloco `:root`.
- Textos: `app/templates/index.html` e `app/templates/register.html`.
- Campos do formulário: `app/forms.py`, `app/models.py`, `app/routes.py` e template do formulário.
- Patrocinadores iniciais: função `_seed_sponsors()` em `app/__init__.py`.
- Imagens: `app/static/img/`.

## Segurança e privacidade

- Troque `SECRET_KEY` e `ADMIN_PASSWORD` em produção.
- Não registre senhas no Git.
- O Render fornece HTTPS na URL pública.
- Restrinja o acesso às credenciais e exportações.
- Faça backup/exportação periódica das inscrições.
- Esta versão não envia e-mail automático; o contato é feito pela equipe a partir do painel/CSV.
