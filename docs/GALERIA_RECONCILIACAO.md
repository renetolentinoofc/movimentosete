# Reconciliação da galeria

A API mantém o banco como catálogo das mídias e verifica se os binários continuam disponíveis no armazenamento configurado.

## Execução manual

Pelo painel administrativo:

```http
POST /api/v1/admin/gallery/reconcile
```

Para repetir a verificação das tarefas pendentes:

```http
POST /api/v1/admin/gallery/reconcile/retry
```

As respostas agrupam as mídias em `completed`, `missing`, `mismatch`, `duplicate`, `orphan` e `error`. Problemas geram registros em `media_reconciliation_tasks`.

## Execução agendada

O mesmo fluxo pode ser executado pelo CLI da API:

```bash
PYTHONPATH=apps/api .venv/bin/flask --app wsgi:app reconcile-gallery --limit 500
```

Em produção, agende esse comando em um job recorrente. A rotina é idempotente: mídias íntegras permanecem concluídas, tarefas com falha acumulam tentativas e arquivos órfãos do Drive não são apagados automaticamente.

## Tratamento

- `missing`: o arquivo não existe mais no armazenamento.
- `mismatch`: o checksum local diverge do catálogo.
- `duplicate`: mais de uma mídia ativa possui o mesmo checksum.
- `orphan`: arquivo do Drive dentro da raiz da galeria não possui registro no banco.
- `error`: o provedor não pôde ser consultado ou não é suportado.

Arquivos ausentes ou órfãos exigem decisão operacional antes de qualquer exclusão. A reconciliação apenas registra a pendência.
