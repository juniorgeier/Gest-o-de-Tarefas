# Gestão de Tarefas Mensais (Python)

Aplicação web para controlar tarefas mensais com histórico.

## O que o app faz

- Cada mês novo nasce com as tarefas em `Pendente`.
- O app abre por padrão no mês de referência anterior.
- Cada tarefa pode ser marcada como:
  - `Pendente`
  - `Em andamento`
  - `Concluído`
- Permite adicionar e remover tarefas base (reflete nos próximos meses).

## Tecnologias

- Python padrão (`http.server`)
- Frontend em HTML, CSS e JS
- Banco:
  - SQLite local (desenvolvimento)
  - PostgreSQL via `DATABASE_URL` (produção)

## Executar localmente

1. Entre na pasta do projeto.
2. Rode:

```bash
python server.py
```

3. Abra:

```text
http://localhost:8000
```

## Deploy gratuito no Render (sem perda em restart/redeploy)

Importante: para não perder dados em restart/redeploy, **não use SQLite local no Render**.
Use `DATABASE_URL` para um Postgres gerenciado (ex.: Supabase).

### 1. Subir projeto para GitHub

- Crie um repositório e envie estes arquivos.
- Este projeto já possui `render.yaml` e `requirements.txt`.

### 2. Criar banco PostgreSQL grátis

- Crie um projeto no Supabase (plano Free).
- Copie a URL de conexão Postgres (`postgresql://...`).
- Se necessário, inclua `sslmode=require` na URL.

### 3. Criar serviço no Render

- Render Dashboard > `New` > `Blueprint` (ou `Web Service` ligado ao GitHub).
- Se usar Blueprint, ele lê `render.yaml` automaticamente.
- Configure variável de ambiente:
  - `DATABASE_URL` = URL do Postgres do Supabase

### 4. Deploy

- O start command é `python server.py`.
- O Render injeta `PORT`; o app já usa essa variável.

### 5. Confirmar funcionamento

- Abra a URL pública `onrender.com`.
- Crie uma tarefa de teste.
- Faça um manual redeploy no Render e confirme que a tarefa continua lá.

## Migrar histórico do SQLite para Postgres

Este projeto inclui o script `migrate_sqlite_to_postgres.py` para migrar seu histórico atual do `tasks.db`.

### Pré-requisitos

- `tasks.db` presente na pasta do projeto
- `DATABASE_URL` apontando para o Postgres (Supabase)

### Rodar migração

No PowerShell:

```powershell
$env:DATABASE_URL="postgresql://USUARIO:SENHA@HOST:5432/postgres?sslmode=require"
python migrate_sqlite_to_postgres.py
```

### O que o script migra

- tabela `base_tasks`
- tabela `months`
- tabela `monthly_tasks`

O script é idempotente (usa upsert), então pode ser executado novamente sem duplicar dados.

## Limitações de gratuito

- Render Free pode "hibernar" após inatividade (volta quando acessa).
- No Supabase Free, projeto parado por muito tempo pode ser pausado; mantenha backup periódico.

## Arquivos principais

- `server.py`
- `index.html`
- `app.js`
- `styles.css`
- `tasks_base.json`
- `render.yaml`
- `requirements.txt`
