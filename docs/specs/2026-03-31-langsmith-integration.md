# Harness Evolver × LangSmith — Guia de Integração (v2)

> **Autor**: Raphael Valdetaro Christi Cordeiro
> **Data**: 2026-03-31
> **Status**: Roadmap (v0.3+)
> **Revisão**: v2 — reescrito para usar langsmith-cli em vez de REST API client custom
> **Pré-requisito**: Design Spec v0.1 (MVP) implementado e validado

---

## 1. Por que integrar

O Harness Evolver tem dois pontos frágeis que o LangSmith resolve:

| Ponto frágil | Hoje (MVP) | Com LangSmith |
|---|---|---|
| **Traces** | `trace_logger.py` manual | Auto-tracing intercepta toda LLM call, chain, tool use, retriever. Zero código. |
| **Eval** | `eval.py` escrito do zero pelo usuário | LLM-as-Judge evaluators pré-construídos (correctness, relevance, helpfulness) |

O paper Meta-Harness mostra que traces são responsáveis por 15pp de diferença (56.7% vs 41.3%).

---

## 2. Opções avaliadas

| Approach | Context cost | Esforço nosso | Resultado |
|---|---|---|---|
| Custom `langsmith_api.py` (spec v1) | 0 tokens (stdlib) | ~7 dias | Funciona mas reinventa a roda |
| LangSmith MCP oficial | 16.100 tokens permanente | 0 dias | Muito pesado em contexto |
| **LangSmith CLI plugin (gigaverse)** | **~200 tokens on-demand** | **~1 dia** | **Melhor custo-benefício** |

**Decisão: usar langsmith-cli.** O proposer já chama `grep`, `cat`, `diff` via subprocess. O `langsmith-cli --json` é mais uma ferramenta diagnóstica no mesmo padrão.

---

## 3. O que é o langsmith-cli

CLI Python (Click-based) que wrapa o LangSmith SDK. Instalado via `uv tool install langsmith-cli`. Funciona como Claude Code plugin com skill de ~200 tokens.

### Instalação

```bash
# CLI
uv tool install langsmith-cli
langsmith-cli auth login

# Claude Code plugin
claude plugin marketplace add gigaverse-app/langsmith-cli
claude plugin install langsmith-cli@langsmith-cli
```

### Comandos relevantes pro proposer

```bash
# Listar runs com falhas (diagnóstico rápido)
langsmith-cli --json runs list --project harness-evolver-v003 --failed --fields id,name,error,inputs

# Ver último erro com detalhes
langsmith-cli --json runs get-latest --project harness-evolver-v003 --failed --fields id,name,error,inputs,outputs

# Estatísticas agregadas (error rate, latência p50/p95/p99)
langsmith-cli --json runs stats --project harness-evolver-v003

# Agrupar falhas por modelo/tag
langsmith-cli --json runs analyze --project harness-evolver-v003 --group-by tag:model --metrics count,error_rate,p95_latency

# Busca full-text em erros
langsmith-cli --json runs list --grep "timeout" --grep-regex --grep-in error --project harness-evolver-v003 --fields id,name,error

# Análise de uso de tokens
langsmith-cli --json runs usage --project harness-evolver-v003 --breakdown model

# Cache local (zero API calls após download)
langsmith-cli --json runs cache download --project harness-evolver-v003
langsmith-cli runs cache grep "retriever.*error" -E --project harness-evolver-v003
```

### Flag `--fields` — o killer feature

Run completo: ~20KB. Com `--fields id,name,error,inputs`: ~2KB. **90%+ de redução** no contexto consumido pelo proposer.

### Flag `--json` — obrigatório pra agentes

Sem `--json`: Rich tables (unparseable). Com `--json`: JSON limpo no stdout, diagnostics no stderr. Sempre primeiro argumento.

---

## 4. Arquitetura nova (v2) vs anterior (v1)

### v1 (spec anterior — eliminada)

```
evaluate.py → langsmith_api.py (urllib) → LangSmith API → filesystem → proposer lê filesystem
                 ↑                              ↑
           nosso código (~250 linhas)     export manual
```

### v2 (nova — muito mais simples)

```
evaluate.py → seta LANGCHAIN_TRACING_V2=true → harness roda → LangSmith captura auto

proposer → langsmith-cli --json runs list ... → diagnóstico direto
                ↑
         já instalado como plugin, zero código nosso
```

**O que eliminamos:** `langsmith_api.py`, `langsmith_adapter.py`, export de traces pro filesystem, merge de scores no scores.json.

**O que mantemos:** evaluate.py seta env vars antes de rodar o harness (3 linhas).

---

## 5. O que muda em cada artefato

### evaluate.py — mudança mínima (3 linhas)

Antes de rodar o harness, setar env vars se LangSmith estiver configurado:

```python
# No cmd_run, antes do loop de tasks:
ls_config = project_config.get("eval", {}).get("langsmith", {})
if ls_config.get("enabled"):
    api_key = os.environ.get(ls_config.get("api_key_env", "LANGSMITH_API_KEY"), "")
    if api_key:
        version = os.path.basename(os.path.dirname(traces_dir))
        langsmith_env = {
            **os.environ,
            "LANGCHAIN_TRACING_V2": "true",
            "LANGCHAIN_API_KEY": api_key,
            "LANGCHAIN_PROJECT": f"{ls_config.get('project_prefix', 'harness-evolver')}-{version}",
        }
```

O harness herda essas env vars via subprocess. Se usa LangChain/LangGraph, o tracing acontece automaticamente.

### init.py — detectar langsmith-cli

```python
def _check_langsmith_cli():
    """Check if langsmith-cli is installed."""
    try:
        r = subprocess.run(["langsmith-cli", "self", "detect"],
                          capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except FileNotFoundError:
        return False

# No init, após detectar stack:
if os.environ.get("LANGSMITH_API_KEY"):
    config["eval"]["langsmith"] = {
        "enabled": True,
        "api_key_env": "LANGSMITH_API_KEY",
        "project_prefix": "harness-evolver",
    }
    if _check_langsmith_cli():
        print("  LangSmith CLI detected — proposer will use it for trace analysis")
    else:
        print("  Recommendation: install langsmith-cli for rich trace analysis:")
        print("    uv tool install langsmith-cli")
        print("    langsmith-cli auth login")
```

### proposer.md — instrução pra usar langsmith-cli

Adicionar na Fase 2 (DIAGNOSTICAR):

```markdown
### LangSmith Traces (when langsmith-cli is available)

If the harness uses LangChain/LangGraph and LangSmith tracing is enabled,
you can query traces directly via `langsmith-cli`:

```bash
# Find failures in this version's project
langsmith-cli --json runs list --project harness-evolver-v{N} --failed --fields id,name,error,inputs

# Get aggregate stats (error rate, latency percentiles)
langsmith-cli --json runs stats --project harness-evolver-v{N}

# Search for specific errors
langsmith-cli --json runs list --grep "pattern" --grep-in error --project harness-evolver-v{N}

# Compare with another version
langsmith-cli --json runs stats --project harness-evolver-v{A}
langsmith-cli --json runs stats --project harness-evolver-v{B}
```

ALWAYS use `--json` flag first and `--fields` to limit output size.
If `langsmith-cli` is not available, use the local traces in `traces/` as usual.
```

### config.json — seção langsmith simplificada

```json
{
  "eval": {
    "langsmith": {
      "enabled": true,
      "api_key_env": "LANGSMITH_API_KEY",
      "project_prefix": "harness-evolver"
    }
  }
}
```

Eliminados: `evaluators`, `export_traces`, `trace_format`, `dataset_id`, `score_weights`. O proposer consulta o LangSmith diretamente quando precisa — não precisamos orquestrar isso.

---

## 6. O que NÃO muda

| Arquivo | Por quê |
|---|---|
| Loop de evolução | O proposer consulta LangSmith internamente |
| state.py | Sem merge de scores — proposer vê scores no LangSmith direto |
| trace_logger.py | Continua como fallback quando LangSmith não está disponível |
| Contrato do harness | --input, --output, --traces-dir, --config não mudam |
| Contrato do eval | --results-dir, --tasks-dir, --scores não mudam |
| install.js | langsmith-cli é instalado pelo usuário separadamente |

---

## 7. Complemento: LangChain Docs MCP

```bash
# Adiciona busca na documentação LangChain/LangGraph/LangSmith
claude mcp add docs-langchain --transport http https://docs.langchain.com/mcp
```

Expõe 1 tool: `search_docs_by_lang_chain`. Complementa o Context7 para o ecossistema LangChain. O proposer pode usar quando precisa de docs específicos de LangChain.

---

## 8. Checklist de implementação (revisada)

### Arquivos modificados

| Arquivo | Mudança | Escopo |
|---|---|---|
| `tools/evaluate.py` | Setar env vars LANGCHAIN_TRACING_V2 antes do harness | ~10 linhas |
| `tools/init.py` | Detectar LANGSMITH_API_KEY + langsmith-cli, configurar | ~20 linhas |
| `agents/harness-evolver-proposer.md` | Bloco "LangSmith Traces" na Fase 2 | ~15 linhas markdown |
| `config.json` template | Seção `langsmith` simplificada | ~5 linhas |

### Arquivos ELIMINADOS (vs spec v1)

| Arquivo | Por quê não precisa mais |
|---|---|
| ~~`tools/langsmith_api.py`~~ | Proposer usa langsmith-cli diretamente |
| ~~`tools/langsmith_adapter.py`~~ | Sem adapter — só env vars |
| ~~`tests/test_langsmith_api.py`~~ | Sem API client pra testar |
| ~~`tests/test_langsmith_adapter.py`~~ | Sem adapter pra testar |

### Testes necessários

| Teste | O que verifica |
|---|---|
| `tests/test_langsmith_init.py` | init.py detecta LANGSMITH_API_KEY e configura |
| Testes existentes de evaluate.py | Verificar que env vars não quebram nada |

### Estimativa de esforço

| Task | Esforço |
|---|---|
| Modificar evaluate.py (env vars) | 1 hora |
| Modificar init.py (detecção) | 1 hora |
| Atualizar proposer.md | 30 min |
| Teste de integração | 1 hora |
| **Total** | **~3.5 horas** |

**Redução vs spec v1:** de ~7 dias para ~3.5 horas. De 2 arquivos novos + 5 hooks para 0 arquivos novos + 1 hook.

---

## 9. Fluxo completo

```bash
# 1. Setup
export LANGSMITH_API_KEY=lsv2_abc123
uv tool install langsmith-cli
langsmith-cli auth login

# 2. Init
/harness-evolve-init --harness chatbot.py --eval eval.py --tasks tasks/
# → Detecta LANGSMITH_API_KEY → habilita tracing no config
# → Detecta langsmith-cli → confirma disponibilidade

# 3. Evolve
/harness-evolve --iterations 10

# Cada iteração:
# a) Proposer lê traces locais (stdout.log, stderr.log, traces/)
# b) Proposer usa langsmith-cli pra diagnóstico rico:
#    langsmith-cli --json runs list --project harness-evolver-v003 --failed --fields error
#    langsmith-cli --json runs stats --project harness-evolver-v003
# c) Proposer propõe novo harness com evidência dos traces
# d) evaluate.py seta LANGCHAIN_TRACING_V2=true → LangSmith captura tudo
# e) Próxima iteração tem traces ricos disponíveis via langsmith-cli
```

---

## 10. Interação com Context7

```
Context7  = KNOWLEDGE (como resolver corretamente?) → docs atuais das bibliotecas
LangSmith = OBSERVABILITY (o que aconteceu?) → traces, erros, latência, tokens

Proposer na Fase 2 (DIAGNOSTICAR):
  1. Lê traces locais (stdout.log, timing.json, per-task outputs)
  2. Se langsmith-cli disponível: runs list --failed, runs stats
  3. Identifica failure mode

Proposer na Fase 3 (PROPOR):
  4. Se Context7 disponível: consulta docs da API correta
  5. Propõe mudança com evidência de traces + docs atuais
```

---

## 11. Referências

- [1] LangSmith CLI Plugin — github.com/gigaverse-app/langsmith-cli
- [2] LangSmith MCP Server (oficial) — github.com/langchain-ai/langsmith-mcp-server
- [3] LangChain Docs MCP — docs.langchain.com/mcp
- [4] Lee et al. "Meta-Harness." arxiv 2603.28052, 2026.
- [5] Harness Evolver Design Spec v0.1. 2026-03-31.
