# Relatório de testes e validação

- Data: 2026-08-12
- Ambiente: Linux, Node 26.4 local (alvo Render Node 24.10), Python 3.14.6, PostgreSQL 18 em container, Chromium 151.
- Dados: somente seeds e dados sintéticos; nenhuma PII real.

## Resultados

| Verificação | Resultado |
|---|---:|
| Ruff API/testes | passou |
| pytest | 13 passaram |
| Vitest/RTL | 2 passaram |
| Playwright desktop + mobile | 16 passaram |
| axe no Playwright | nenhuma violação séria/crítica na home |
| TypeScript estrito | passou |
| ESLint | passou, com 4 avisos não bloqueantes documentados abaixo |
| Next.js produção | passou, 23 páginas/rotas |
| `npm audit --audit-level=high` | 0 vulnerabilidades |
| `pip-audit` | nenhuma vulnerabilidade conhecida |
| Gunicorn smoke test | iniciou; health e 11 categorias responderam |
| PostgreSQL 18 | downgrade, upgrade, seed repetido e `flask db check` passaram |

## Banco e seeds

A revisão `784a42a09e36` cria 58 tabelas da aplicação (59 no schema incluindo `alembic_version`). Depois de duas execuções do seed: 11 categorias, 8 papéis, 4 parceiros e 3 produtos, sem duplicação. O ciclo de downgrade e novo upgrade foi executado em banco local descartável; não houve alteração em recurso externo.

## Lighthouse mobile de produção

Executado contra `next start` e Gunicorn locais com Lighthouse 13 e Chromium 151:

- performance: 98;
- acessibilidade: 100;
- SEO: 100;
- LCP simulado: 2,4 s;
- CLS: 0;
- transferência total da home: 325 KiB.

INP depende de dados de campo e não pode ser validado com precisão por uma única execução de laboratório.

## Avisos conhecidos

O ESLint emite três avisos por `<img>` em mídia remota administrável, pois as dimensões/domínios só existem em runtime; a API armazena dimensões e os assets de marca locais usam `next/image`. O React Compiler ignora memoização automática do formulário que usa `watch` do React Hook Form, conforme o aviso oficial da integração; não é erro de tipo ou runtime.

## Cobertura ainda necessária antes do lançamento externo

Os testes automatizados cobrem os riscos críticos implementados, mas a aprovação operacional final ainda deve incluir: teste concorrente de lances com a flag ligada em ambiente jurídico aprovado; webhook do gateway escolhido; reconciliação real do Drive; revisão manual completa por leitor de tela; e smoke test no domínio final após o primeiro deploy autorizado.
