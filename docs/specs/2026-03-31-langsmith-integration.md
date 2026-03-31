# Harness Evolver × LangSmith — Guia de Integração

> **Autor**: Raphael Valdetaro Christi Cordeiro  
> **Data**: 2026-03-31  
> **Status**: Roadmap (v0.3+)  
> **Pré-requisito**: Design Spec v0.1 (MVP) implementado e validado  

---

## 1. Por que integrar

O Harness Evolver tem dois pontos frágeis que o LangSmith resolve diretamente:

| Ponto frágil | Hoje (MVP) | Com LangSmith |
|---|---|---|
| **Traces** | `trace_logger.py` manual — o usuário decide o que logar | Auto-tracing intercepta toda LLM call, chain, tool use, retriever. Zero código. |
| **Eval** | `eval.py` escrito do zero pelo usuário. Funciona pra exact match, falha pra avaliação semântica | LLM-as-Judge evaluators pré-construídos (correctness, relevance, helpfulness) + custom evaluators |

O paper Meta-Harness [1] mostra que traces são responsáveis por 15pp de diferença na performance do proposer (56.7% com traces completos vs 41.3% com scores-only). Quanto mais ricos os traces, melhor o diagnóstico contrafactual.

---

## 2. Princípios da integração

1. **LangSmith é opcional** — o MVP continua funcionando com JSONs locais e `trace_logger.py`. A integração é um adapter que enriquece, não substitui.
2. **O proposer não muda** — ele continua lendo o filesystem. O que muda é o conteúdo dos traces e scores.
3. **Sem vendor lock-in** — se o usuário desligar o LangSmith, perde riqueza de traces mas o loop continua rodando.
4. **Zero LangSmith SDK no core** — os tools Python são stdlib-only. A integração usa a REST API do LangSmith diretamente (requests stdlib via `urllib`), ou opcionalmente o SDK se o usuário tiver `langsmith` instalado.

---

## 3. Arquitetura antes vs depois

```
MVP (sem LangSmith):

harness.py ──► trace_logger.py (manual) ──► traces/ (stdout, stderr, extra/)
                                                │
eval.py (user writes) ──────────────────────► scores.json
                                                │
                                      proposer lê filesystem


Com LangSmith:

harness.py (LangGraph/LangChain)
    │
    ├──► LangSmith auto-tracing (LANGCHAIN_TRACING_V2=true)
    │         │
    │         ▼
    │    LangSmith Cloud ◄── traces ricos (cada LLM call, tool, retriever)
    │         │
    │         ▼
    └──► evaluate.py exporta traces via API
              │
              ▼
         traces/langsmith/        ◄── JSONs exportados pro filesystem
              │
              ▼
         LangSmith Evaluators     ◄── correctness, relevance, custom
              │
              ▼
         scores.json (enriched)   ◄── scores com breakdown por evaluator
              │
              ▼
         proposer lê filesystem   ◄── NENHUMA mudança no proposer
```

---

## 4. O que muda no config.json

### Antes (MVP)

```json
{
  "version": "0.1.0",
  "harness": { ... },
  "eval": { ... },
  "evolution": { ... },
  "paths": { ... }
}
```

### Depois (com LangSmith)

```json
{
  "version": "0.2.0",
  "harness": { ... },
  "eval": {
    "command": "python3 eval.py",
    "args": ["--results-dir", "{results_dir}", "--tasks-dir", "{tasks_dir}", "--scores", "{scores}"],
    "langsmith": {
      "enabled": true,
      "api_key_env": "LANGSMITH_API_KEY",
      "project_prefix": "harness-evolver",
      "dataset_id": null,
      "evaluators": {
        "builtin": ["correctness", "relevance", "helpfulness"],
        "custom": []
      },
      "export_traces": true,
      "trace_format": "jsonl"
    }
  },
  "evolution": { ... },
  "paths": { ... }
}
```

### Campos novos

| Campo | Tipo | Default | Descrição |
|---|---|---|---|
| `langsmith.enabled` | bool | `false` | Liga/desliga a integração. Se false, tudo funciona como no MVP. |
| `langsmith.api_key_env` | string | `"LANGSMITH_API_KEY"` | Nome da env var que contém a API key. Nunca armazenar a key no config. |
| `langsmith.project_prefix` | string | `"harness-evolver"` | Prefixo dos projects no LangSmith. Cada versão cria um project `{prefix}-v{N}`. |
| `langsmith.dataset_id` | string\|null | `null` | Se fornecido, usa dataset do LangSmith em vez de `eval/tasks/`. Se null, usa tasks locais. |
| `langsmith.evaluators.builtin` | list[string] | `[]` | Evaluators pré-construídos do LangSmith a usar. |
| `langsmith.evaluators.custom` | list[string] | `[]` | Paths pra evaluators custom (Python callables). |
| `langsmith.export_traces` | bool | `true` | Se true, exporta traces do LangSmith pro filesystem pra o proposer ler. |
| `langsmith.trace_format` | string | `"jsonl"` | Formato de export: `"jsonl"` (um JSON por linha) ou `"json"` (array). |

---

## 5. O que muda em cada artefato

### 5.1 evaluate.py (tool principal)

O `evaluate.py` é o orquestrador. Com LangSmith, ele ganha 3 capacidades novas:

**A) Setup do tracing antes de rodar o harness**

```python
def setup_langsmith_tracing(config, version):
    """Seta env vars pra LangSmith auto-tracing antes de chamar o harness."""
    ls_config = config.get("eval", {}).get("langsmith", {})
    if not ls_config.get("enabled"):
        return

    api_key = os.environ.get(ls_config.get("api_key_env", "LANGSMITH_API_KEY"))
    if not api_key:
        print("WARNING: LangSmith enabled but API key not found. Running without tracing.")
        return

    # O harness herda essas env vars
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGCHAIN_PROJECT"] = f"{ls_config['project_prefix']}-{version}"
```

O harness não precisa saber nada sobre LangSmith. Se ele usa LangChain/LangGraph, o tracing acontece automaticamente via env vars herdadas pelo subprocess.

**B) Export de traces após rodar o harness**

```python
def export_langsmith_traces(config, version, traces_dir):
    """Exporta traces do LangSmith pro filesystem pra o proposer ler."""
    ls_config = config["eval"]["langsmith"]
    if not ls_config.get("export_traces"):
        return

    api_key = os.environ.get(ls_config.get("api_key_env"))
    project_name = f"{ls_config['project_prefix']}-{version}"

    # Busca runs do project via REST API (stdlib urllib)
    runs = langsmith_api_get_runs(api_key, project_name)

    # Salva no filesystem
    langsmith_dir = os.path.join(traces_dir, "langsmith")
    os.makedirs(langsmith_dir, exist_ok=True)

    for run in runs:
        # Cada run contém: inputs, outputs, latency, tokens, child_runs (tools, retrievers)
        run_file = os.path.join(langsmith_dir, f"{run['id']}.json")
        with open(run_file, "w") as f:
            json.dump({
                "run_id": run["id"],
                "run_type": run["run_type"],       # "llm", "chain", "tool", "retriever"
                "name": run["name"],
                "inputs": run.get("inputs"),        # o prompt enviado
                "outputs": run.get("outputs"),      # a resposta recebida
                "error": run.get("error"),           # se crashou
                "latency_ms": run.get("latency_ms"),
                "tokens": {
                    "prompt": run.get("prompt_tokens", 0),
                    "completion": run.get("completion_tokens", 0),
                    "total": run.get("total_tokens", 0)
                },
                "child_runs": len(run.get("child_run_ids", [])),
                "feedback": run.get("feedback_stats"),  # scores dos evaluators
                "metadata": run.get("extra", {}).get("metadata", {})
            }, f, indent=2)

    # Resumo consolidado pra leitura rápida do proposer
    summary_file = os.path.join(langsmith_dir, "_summary.json")
    with open(summary_file, "w") as f:
        json.dump({
            "total_runs": len(runs),
            "run_types": {rt: sum(1 for r in runs if r["run_type"] == rt)
                         for rt in set(r["run_type"] for r in runs)},
            "errors": [{"run_id": r["id"], "error": r["error"]}
                      for r in runs if r.get("error")],
            "total_tokens": sum(r.get("total_tokens", 0) for r in runs),
            "avg_latency_ms": sum(r.get("latency_ms", 0) for r in runs) / len(runs) if runs else 0
        }, f, indent=2)
```

**C) Rodar evaluators do LangSmith após o eval.py do usuário**

```python
def run_langsmith_evaluators(config, version, results_dir, tasks_dir):
    """Roda evaluators do LangSmith e enriquece o scores.json."""
    ls_config = config["eval"]["langsmith"]
    evaluators = ls_config.get("evaluators", {})

    if not evaluators.get("builtin") and not evaluators.get("custom"):
        return {}

    api_key = os.environ.get(ls_config.get("api_key_env"))
    project_name = f"{ls_config['project_prefix']}-{version}"

    ls_scores = {}

    for evaluator_name in evaluators.get("builtin", []):
        # Chama LangSmith evaluate API
        result = langsmith_api_evaluate(
            api_key=api_key,
            project_name=project_name,
            evaluator=evaluator_name
        )
        ls_scores[f"langsmith_{evaluator_name}"] = result["aggregate_score"]

    return ls_scores
```

### 5.2 scores.json (enriquecido)

```json
{
  "combined_score": 0.85,
  "accuracy": 0.90,
  "latency_avg_ms": 230,
  "per_task": {
    "task_001": {"score": 1.0},
    "task_002": {"score": 0.0, "error": "wrong category"}
  },
  "langsmith": {
    "correctness": 0.82,
    "relevance": 0.91,
    "helpfulness": 0.78,
    "total_tokens": 4523,
    "total_cost_usd": 0.034,
    "avg_latency_ms": 1240
  }
}
```

O proposer agora tem acesso a dimensões que não existiam antes: custo por versão, latência real, e scores semânticos.

### 5.3 Traces no filesystem (novo diretório)

```
harnesses/v003/traces/
├── stdout.log                    # Existente (MVP)
├── stderr.log                    # Existente (MVP)
├── timing.json                   # Existente (MVP)
├── task_001/                     # Existente (MVP)
│   ├── input.json
│   ├── output.json
│   └── extra/
├── langsmith/                    # NOVO
│   ├── _summary.json             # Resumo: total runs, erros, tokens, latência
│   ├── run_abc123.json           # Run completo: inputs, outputs, tokens, latency
│   ├── run_def456.json           # Cada LLM call, tool call, retriever call
│   └── ...
```

O proposer na Fase 2 (DIAGNOSTICAR) agora pode:

```
1. Ler traces/langsmith/_summary.json  → "v003 usou 4523 tokens, 3 erros, latência média 1240ms"
2. grep traces/langsmith/ -l "error"   → encontra quais runs falharam
3. cat traces/langsmith/run_abc123.json → vê o prompt exato e a resposta do LLM
4. Comparar com v002: "v002 usava prompt de 200 tokens, v003 mudou pra 800 tokens — isso explica a latência"
```

### 5.4 Proposer Agent (NÃO muda)

O `agents/harness-evolver-proposer.md` não precisa de nenhuma mudança. Ele já tem acesso irrestrito ao filesystem via `grep`, `cat`, `diff`. Os traces do LangSmith aparecem como mais arquivos JSON no filesystem — o proposer os descobre naturalmente.

A única adição seria uma linha na Fase 2 do proposer:

```markdown
- Se existir `traces/langsmith/`, ler `_summary.json` primeiro para overview.
  Depois fazer grep cirúrgico nos runs relevantes.
```

### 5.5 init.py (mudança mínima)

Detectar se `LANGSMITH_API_KEY` existe no ambiente e sugerir `langsmith.enabled: true` no config:

```python
def detect_langsmith():
    if os.environ.get("LANGSMITH_API_KEY"):
        return {
            "enabled": True,
            "api_key_env": "LANGSMITH_API_KEY",
            "project_prefix": "harness-evolver",
            "evaluators": {"builtin": ["correctness"], "custom": []},
            "export_traces": True,
            "trace_format": "jsonl"
        }
    return {"enabled": False}
```

### 5.6 state.py (mudança mínima)

Incluir scores do LangSmith no `summary.json`:

```python
def update_summary(version, scores):
    entry = {
        "version": version,
        "combined_score": scores["combined_score"],
        "parent": determine_parent(version)
    }

    # Se LangSmith scores existem, incluir
    if "langsmith" in scores:
        entry["langsmith_correctness"] = scores["langsmith"].get("correctness")
        entry["total_tokens"] = scores["langsmith"].get("total_tokens")
        entry["cost_usd"] = scores["langsmith"].get("total_cost_usd")

    # ... append to summary.json
```

---

## 6. Integração com LangSmith Datasets

### Hoje (MVP): tasks locais

```
/harness-evolve-init --harness harness.py --eval eval.py --tasks ./tasks/
```

### Com LangSmith: dataset remoto

```
/harness-evolve-init --harness harness.py --eval eval.py --langsmith-dataset ds_abc123
```

O `init.py` faz pull do dataset via API e salva em `eval/tasks/`:

```python
def pull_langsmith_dataset(dataset_id, tasks_dir):
    """Baixa examples do LangSmith dataset e salva como task JSONs."""
    api_key = os.environ.get("LANGSMITH_API_KEY")
    examples = langsmith_api_get_examples(api_key, dataset_id)

    for example in examples:
        task = {
            "id": example["id"],
            "input": example["inputs"],
            "expected": example["outputs"],
            "metadata": {
                "langsmith_dataset_id": dataset_id,
                "langsmith_example_id": example["id"],
                "created_at": example.get("created_at")
            }
        }
        task_path = os.path.join(tasks_dir, f"{example['id']}.json")
        with open(task_path, "w") as f:
            json.dump(task, f, indent=2)
```

Vantagem: o dataset fica versionado no LangSmith. O time pode adicionar examples pelo UI do LangSmith, e o evolver puxa automaticamente na próxima rodada.

---

## 7. LLM-as-Judge: evaluators detalhados

### Evaluators built-in do LangSmith

| Evaluator | O que avalia | Quando usar |
|---|---|---|
| `correctness` | Resposta factualmente correta dado o expected | Chatbot, QA, RAG |
| `relevance` | Resposta relevante à pergunta | RAG, search |
| `helpfulness` | Resposta útil pro usuário | Chatbot, assistente |
| `harmfulness` | Resposta contém conteúdo nocivo | Safety, compliance |
| `coherence` | Resposta coerente e bem estruturada | Geração de texto |
| `conciseness` | Resposta concisa sem informação desnecessária | Resumos, extrações |

### Como o evaluate.py orquestra

```python
def run_full_evaluation(config, version):
    """Fluxo completo de avaliação."""

    # 1. Roda o eval.py do usuário (scores básicos: accuracy, exact match, etc.)
    user_scores = run_user_eval(config, version)

    # 2. Se LangSmith habilitado, roda evaluators adicionais
    ls_scores = {}
    if config["eval"].get("langsmith", {}).get("enabled"):
        ls_scores = run_langsmith_evaluators(config, version)

    # 3. Merge scores
    final_scores = {**user_scores}
    if ls_scores:
        final_scores["langsmith"] = ls_scores

        # Recalcula combined_score considerando LangSmith
        # Peso configurável no config.json
        weights = config["eval"].get("score_weights", {
            "user_score": 0.6,
            "langsmith_avg": 0.4
        })
        ls_avg = sum(ls_scores.values()) / len(ls_scores) if ls_scores else 0
        final_scores["combined_score"] = (
            user_scores["combined_score"] * weights["user_score"] +
            ls_avg * weights["langsmith_avg"]
        )

    return final_scores
```

### Config de pesos

```json
{
  "eval": {
    "score_weights": {
      "user_score": 0.6,
      "langsmith_avg": 0.4
    }
  }
}
```

O usuário controla quanto peso dar pros evaluators do LangSmith vs o score do eval.py dele. Default: 60% user, 40% LangSmith. Pode ajustar conforme a confiança nos evaluators.

---

## 8. Comparison View no LangSmith

Cada versão do harness cria um project no LangSmith: `harness-evolver-v001`, `harness-evolver-v002`, etc. O LangSmith permite comparar experiments side-by-side nativamente.

O que o usuário ganha sem nenhum código:
- Tabela comparativa de todas as versões
- Drill-down por example: "task_003 acertou em v001 mas errou em v003 — por quê?"
- Histograma de latência por versão
- Custo acumulado por versão
- Diff de outputs entre versões

### Link automático no REPORTAR

O step 5 (REPORTAR) do loop passa a incluir o link:

```
Iteração 3: v003 scored 0.71 (best: v003 at 0.71)
✓ Novo melhor: 0.71
📊 LangSmith: https://smith.langchain.com/o/{org}/projects/p/harness-evolver-v003
```

---

## 9. Annotation Queues (v0.5+)

### Conceito

O LangSmith permite que humanos revisem e anotem outputs. Isso abre um fluxo que o Meta-Harness não tem: **human-in-the-loop no eval**.

### Fluxo

```
1. Evolver roda 10 iterações automaticamente
2. Resultados aparecem no LangSmith
3. Humano revisa outputs no LangSmith UI:
   - Marca outputs errados que o eval automático não pegou
   - Adiciona annotations ("esta resposta está tecnicamente correta mas confusa")
   - Adiciona novos examples ao dataset
4. Próxima rodada do evolver usa o dataset atualizado
5. Proposer vê as annotations nos traces exportados
```

### Implementação

O `evaluate.py` exporta annotations junto com os traces:

```python
def export_annotations(config, version, traces_dir):
    """Exporta human annotations do LangSmith."""
    annotations = langsmith_api_get_feedback(api_key, project_name)

    annotations_file = os.path.join(traces_dir, "langsmith", "_annotations.json")
    with open(annotations_file, "w") as f:
        json.dump([{
            "run_id": a["run_id"],
            "key": a["key"],           # "correctness", "user_score", custom
            "score": a["score"],
            "comment": a["comment"],    # Human comment
            "annotator": a.get("created_by")
        } for a in annotations], f, indent=2)
```

O proposer na Fase 2 pode ler `_annotations.json` e descobrir: "O humano marcou que task_005 estava errado mesmo com score 1.0 no exact match — o output estava no formato errado."

---

## 10. API LangSmith — funções necessárias (stdlib urllib)

Todas as chamadas à API do LangSmith serão feitas com `urllib` (stdlib), sem dependência do SDK `langsmith`. O arquivo `tools/langsmith_api.py` encapsula:

```python
"""LangSmith REST API client. Stdlib-only (urllib + json)."""

import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError

LANGSMITH_BASE_URL = "https://api.smith.langchain.com"

def _request(method, path, api_key, data=None):
    """Helper pra chamadas à API."""
    url = f"{LANGSMITH_BASE_URL}{path}"
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json"
    }
    body = json.dumps(data).encode() if data else None
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"LangSmith API error {e.code}: {error_body}")


def get_runs(api_key, project_name, run_type=None, limit=100):
    """Lista runs de um project."""
    params = {"project_name": project_name, "limit": limit}
    if run_type:
        params["run_type"] = run_type
    return _request("POST", "/api/v1/runs/query", api_key, params)


def get_dataset_examples(api_key, dataset_id, limit=1000):
    """Lista examples de um dataset."""
    return _request("GET", f"/api/v1/datasets/{dataset_id}/examples?limit={limit}", api_key)


def create_project(api_key, project_name):
    """Cria um project (se não existir)."""
    return _request("POST", "/api/v1/projects", api_key, {"name": project_name})


def get_feedback(api_key, project_name):
    """Lista feedback/annotations de um project."""
    runs = get_runs(api_key, project_name)
    run_ids = [r["id"] for r in runs.get("runs", [])]
    if not run_ids:
        return []
    return _request("POST", "/api/v1/feedback/query", api_key, {"run_ids": run_ids})


def run_evaluator(api_key, project_name, evaluator_name):
    """Roda um evaluator built-in num project."""
    return _request("POST", "/api/v1/evaluators/run", api_key, {
        "project_name": project_name,
        "evaluator": evaluator_name
    })
```

---

## 11. Checklist de implementação

### Novos arquivos

| Arquivo | Descrição | Prioridade |
|---|---|---|
| `tools/langsmith_api.py` | Client REST API stdlib-only | P0 da integração |
| `tools/langsmith_adapter.py` | Adapter que conecta evaluate.py ao LangSmith | P0 da integração |

### Arquivos modificados

| Arquivo | Mudança | Escopo |
|---|---|---|
| `tools/evaluate.py` | Adicionar setup_langsmith_tracing(), export_langsmith_traces(), run_langsmith_evaluators() | Médio — 3 funções novas, fluxo existente preservado |
| `tools/init.py` | Detectar LANGSMITH_API_KEY, sugerir config, suporte a --langsmith-dataset | Pequeno |
| `tools/state.py` | Incluir langsmith scores no summary.json | Mínimo — 5 linhas |
| `config.json` template | Adicionar seção langsmith | Mínimo |
| `agents/harness-evolver-proposer.md` | Adicionar 1 linha: "Se existir traces/langsmith/, ler _summary.json primeiro" | Mínimo |
| `skills/harness-evolve/SKILL.md` | Adicionar link do LangSmith no step REPORTAR | Mínimo |
| `skills/harness-evolve-init/SKILL.md` | Suporte a --langsmith-dataset flag | Pequeno |

### Nada muda

| Arquivo | Por quê |
|---|---|
| `install.js` | LangSmith não requer instalação de nada novo |
| `trace_logger.py` | Continua funcionando como fallback quando LangSmith está desligado |
| `state.py` (core) | Só append de campos opcionais |
| Proposer workflow (4 fases) | O proposer descobre traces do LangSmith naturalmente via filesystem |
| Contrato do harness | --input, --output, --traces-dir, --config não mudam |
| Contrato do eval | --results-dir, --tasks-dir, --scores não mudam |

---

## 12. Fluxo completo com LangSmith (exemplo)

```bash
# 1. Setup
export LANGSMITH_API_KEY=lsv2_abc123

# 2. Init com dataset do LangSmith
/harness-evolve-init \
  --harness ./chatbot.py \
  --eval ./eval_chatbot.py \
  --langsmith-dataset ds_customer_service_v2

# 3. O init.py:
#    - Detecta LANGSMITH_API_KEY → habilita langsmith no config
#    - Puxa 50 examples do dataset ds_customer_service_v2 → eval/tasks/
#    - Configura evaluators: correctness + relevance
#    - Roda baseline eval → summary.json

# 4. Evolve
/harness-evolve --iterations 10

# 5. A cada iteração:
#    a) Proposer lê filesystem (inclui traces/langsmith/ das versões anteriores)
#    b) Proposer propõe novo harness.py
#    c) evaluate.py seta LANGCHAIN_TRACING_V2=true antes de chamar harness
#    d) Harness roda → LangSmith captura todas as LLM calls automaticamente
#    e) evaluate.py exporta traces do LangSmith pro filesystem
#    f) evaluate.py roda eval.py do usuário (accuracy)
#    g) evaluate.py roda LangSmith evaluators (correctness, relevance)
#    h) Merge scores → scores.json
#    i) Reporta: "v003 scored 0.78 | LangSmith correctness: 0.82 | 📊 link"

# 6. Resultado: melhor harness com traces ricos, scores multi-dimensionais,
#    e histórico completo visível no LangSmith UI
```

---

## 13. Testes da integração

### Test 1: LangSmith desligado (regressão)

```bash
# Sem LANGSMITH_API_KEY → tudo funciona como MVP
unset LANGSMITH_API_KEY
/harness-evolve-init --harness harness.py --eval eval.py --tasks ./tasks/
/harness-evolve --iterations 3
# Deve rodar sem erros, sem traces/langsmith/, scores.json sem campo "langsmith"
```

### Test 2: LangSmith ligado, harness sem LangChain

```bash
# Com LANGSMITH_API_KEY mas harness não usa LangChain
# → Auto-tracing não captura nada (sem LangChain, sem traces automáticos)
# → Evaluators rodam normalmente nos outputs
# → traces/langsmith/ existe mas tem poucos runs
```

### Test 3: LangSmith ligado, harness com LangGraph

```bash
# Cenário ideal: harness usa LangGraph
# → Auto-tracing captura cada node, edge, LLM call, tool call
# → traces/langsmith/ rico com dezenas de runs por task
# → Proposer tem dados pra diagnóstico profundo
```

### Test 4: LangSmith API down

```bash
# API fora do ar → evaluate.py captura o erro, loga warning, continua sem LangSmith
# O loop não deve parar por causa de falha no LangSmith
```

---

## 14. Roadmap de integração

| Versão | Feature | Estimativa |
|---|---|---|
| **v0.3** | `langsmith_api.py` + auto-tracing + export de traces | 3 dias |
| **v0.3** | LangSmith evaluators (builtin) | 2 dias |
| **v0.3** | Dataset pull via --langsmith-dataset | 1 dia |
| **v0.3** | Merge de scores (user + LangSmith) | 1 dia |
| **v0.4** | Link automático no REPORTAR | 0.5 dia |
| **v0.4** | Comparison view (instructions pro usuário) | 0.5 dia |
| **v0.5** | Annotation export pro proposer | 2 dias |
| **v0.5** | Dataset sync bidirecional (local ↔ LangSmith) | 3 dias |

**Total v0.3: ~7 dias de trabalho.**

---

## 15. Referências

- [1] Lee et al. "Meta-Harness: End-to-End Optimization of Model Harnesses." arxiv 2603.28052, 2026.
- [2] LangSmith Docs — Tracing. https://docs.smith.langchain.com/observability
- [3] LangSmith Docs — Evaluation. https://docs.smith.langchain.com/evaluation
- [4] LangSmith Docs — Datasets. https://docs.smith.langchain.com/evaluation/how_to_guides/manage_datasets_in_application
- [5] LangSmith Docs — Human Feedback. https://docs.smith.langchain.com/observability/how_to_guides/annotation_queues
- [6] LangSmith REST API Reference. https://api.smith.langchain.com/redoc
- [7] LangChain — Auto-tracing. https://docs.smith.langchain.com/observability/how_to_guides/tracing/trace_with_langchain
- [8] Harness Evolver Design Spec v0.1. 2026-03-31.
