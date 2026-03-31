# Harness Evolver × Context7 — Guia de Integração

> **Autor**: Raphael Valdetaro Christi Cordeiro  
> **Data**: 2026-03-31  
> **Status**: Roadmap (v0.4+)  
> **Pré-requisito**: MVP (Tasks 1-11) implementado  
> **Depende de**: LangSmith integration (v0.3) — NÃO. Context7 é independente.

---

## 1. Por que integrar

O proposer tem uma limitação silenciosa: propõe código baseado no **knowledge de treino** do modelo. Se o harness do usuário usa LangGraph 0.3, o proposer sabe LangGraph — mas da versão que estava no training data. Ele pode:

- Propor uma API deprecated
- Perder um parâmetro novo que resolveria o problema
- Inventar um método que não existe
- Ignorar uma feature nova que é a solução ideal

**Os traces dizem o que falhou. A documentação diz como resolver corretamente.**

Exemplo concreto: o proposer diagnostica "o retriever está retornando chunks irrelevantes" e propõe uma solução baseada no que ele "lembra" de LangChain. Com Context7, ele consultaria a documentação atual e descobriria que existe um `ContextualCompressionRetriever` — com a API correta, parâmetros corretos, e um exemplo funcional.

---

## 2. O que é o Context7

Context7 é um MCP server da Upstash que puxa documentação atualizada e version-specific direto dos repositórios oficiais das bibliotecas e injeta no contexto do LLM.

**Duas tools expostas:**

| Tool | O que faz |
|---|---|
| `resolve-library-id` | Converte nome da biblioteca pra ID compatível com Context7 (ex: "langchain" → `/langchain-ai/langchain`) |
| `query-docs` / `get-library-docs` | Busca documentação relevante pra uma query específica dentro de uma biblioteca |

**Já existe como plugin Claude Code:**

```
# MCP server (base)
claude mcp add context7 -- npx -y @upstash/context7-mcp@latest

# Plugin com skills + agents + commands (mais features)
/plugin marketplace add upstash/context7
/plugin install context7-plugin@context7-marketplace
```

O plugin adiciona:
- **Skill `documentation-lookup`** — auto-trigger quando o prompt menciona uma biblioteca
- **Agent `docs-researcher`** — subagent isolado que faz lookups sem poluir o contexto principal
- **Command `/context7:docs`** — lookup manual on-demand

---

## 3. Por que a integração é mais simples que LangSmith

Diferença fundamental: **não precisamos escrever nenhum adapter**.

O Context7 é um MCP server. O proposer é um subagent do Claude Code. Subagents do Claude Code já têm acesso a todos os MCP servers configurados pelo usuário. Então o proposer **já pode usar** o Context7 — basta estar instalado.

O que o nosso plugin faz é:
1. **Detectar a stack** do harness do usuário (analisar imports)
2. **Instruir o proposer** a consultar docs antes de escrever código
3. **Sugerir instalação** do Context7 se não estiver presente
4. Opcionalmente **salvar os docs consultados** no filesystem pra referência

Comparação com LangSmith:

| Aspecto | LangSmith | Context7 |
|---|---|---|
| O que precisamos escrever | `langsmith_api.py` (client REST), `langsmith_adapter.py`, hooks no evaluate.py | `detect_stack.py` (40 linhas), 3 linhas no proposer.md |
| Modifica evaluate.py | Sim (5 hooks) | Não |
| Modifica o loop | Não | Não |
| Modifica o proposer | 1 linha | 3 linhas |
| Novo arquivo Python | 2 | 1 |
| Dependência externa | LangSmith API key | Context7 MCP server (ou nada — é opcional) |

---

## 4. O que muda na arquitetura

### Novo arquivo: `tools/detect_stack.py`

```python
"""Detecta a stack do harness analisando imports e dependências.
Stdlib-only. Analisa AST do Python pra extrair imports."""

import ast
import json
import os
import sys

# Bibliotecas conhecidas e seus IDs Context7
KNOWN_LIBRARIES = {
    # AI/ML Frameworks
    "langchain": {
        "context7_id": "/langchain-ai/langchain",
        "display": "LangChain",
        "modules": ["langchain", "langchain_core", "langchain_openai",
                     "langchain_anthropic", "langchain_community"]
    },
    "langgraph": {
        "context7_id": "/langchain-ai/langgraph",
        "display": "LangGraph",
        "modules": ["langgraph"]
    },
    "llamaindex": {
        "context7_id": "/run-llama/llama_index",
        "display": "LlamaIndex",
        "modules": ["llama_index"]
    },
    "openai": {
        "context7_id": "/openai/openai-python",
        "display": "OpenAI Python SDK",
        "modules": ["openai"]
    },
    "anthropic": {
        "context7_id": "/anthropics/anthropic-sdk-python",
        "display": "Anthropic Python SDK",
        "modules": ["anthropic"]
    },
    "dspy": {
        "context7_id": "/stanfordnlp/dspy",
        "display": "DSPy",
        "modules": ["dspy"]
    },
    "crewai": {
        "context7_id": "/crewAIInc/crewAI",
        "display": "CrewAI",
        "modules": ["crewai"]
    },
    "autogen": {
        "context7_id": "/microsoft/autogen",
        "display": "AutoGen",
        "modules": ["autogen"]
    },

    # Vector Stores
    "chromadb": {
        "context7_id": "/chroma-core/chroma",
        "display": "ChromaDB",
        "modules": ["chromadb"]
    },
    "pinecone": {
        "context7_id": "/pinecone-io/pinecone-python-client",
        "display": "Pinecone",
        "modules": ["pinecone"]
    },
    "qdrant": {
        "context7_id": "/qdrant/qdrant",
        "display": "Qdrant",
        "modules": ["qdrant_client"]
    },
    "weaviate": {
        "context7_id": "/weaviate/weaviate",
        "display": "Weaviate",
        "modules": ["weaviate"]
    },

    # Web Frameworks
    "fastapi": {
        "context7_id": "/fastapi/fastapi",
        "display": "FastAPI",
        "modules": ["fastapi"]
    },
    "flask": {
        "context7_id": "/pallets/flask",
        "display": "Flask",
        "modules": ["flask"]
    },
    "pydantic": {
        "context7_id": "/pydantic/pydantic",
        "display": "Pydantic",
        "modules": ["pydantic"]
    },

    # Data
    "pandas": {
        "context7_id": "/pandas-dev/pandas",
        "display": "Pandas",
        "modules": ["pandas"]
    },
    "numpy": {
        "context7_id": "/numpy/numpy",
        "display": "NumPy",
        "modules": ["numpy"]
    },
}


def detect_from_file(filepath):
    """Analisa imports de um arquivo Python e retorna stack detectada."""
    with open(filepath) as f:
        try:
            tree = ast.parse(f.read())
        except SyntaxError:
            return {}

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])

    detected = {}
    for lib_key, lib_info in KNOWN_LIBRARIES.items():
        found = imports & set(lib_info["modules"])
        if found:
            detected[lib_key] = {
                "context7_id": lib_info["context7_id"],
                "display": lib_info["display"],
                "modules_found": sorted(found)
            }

    return detected


def detect_from_directory(directory):
    """Analisa todos os .py num diretório e consolida a stack."""
    all_detected = {}
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(".py"):
                filepath = os.path.join(root, f)
                file_detected = detect_from_file(filepath)
                for lib_key, lib_info in file_detected.items():
                    if lib_key not in all_detected:
                        all_detected[lib_key] = lib_info
                    else:
                        existing = set(all_detected[lib_key]["modules_found"])
                        existing.update(lib_info["modules_found"])
                        all_detected[lib_key]["modules_found"] = sorted(existing)
    return all_detected


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Detect stack from Python files")
    parser.add_argument("path", help="File or directory to analyze")
    parser.add_argument("--output", "-o", help="Output JSON path")
    args = parser.parse_args()

    if os.path.isfile(args.path):
        result = detect_from_file(args.path)
    else:
        result = detect_from_directory(args.path)

    output = json.dumps(result, indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)
```

### config.json — nova seção `stack`

Gerada automaticamente pelo `init.py` usando `detect_stack.py`:

```json
{
  "version": "0.1.0",
  "harness": { "..." : "..." },
  "eval": { "..." : "..." },
  "evolution": { "..." : "..." },
  "paths": { "..." : "..." },

  "stack": {
    "detected": {
      "langchain": {
        "context7_id": "/langchain-ai/langchain",
        "display": "LangChain",
        "modules_found": ["langchain", "langchain_openai"]
      },
      "langgraph": {
        "context7_id": "/langchain-ai/langgraph",
        "display": "LangGraph",
        "modules_found": ["langgraph"]
      },
      "chromadb": {
        "context7_id": "/chroma-core/chroma",
        "display": "ChromaDB",
        "modules_found": ["chromadb"]
      }
    },
    "documentation_hint": "use context7",
    "auto_detected": true
  }
}
```

### init.py — mudanças

3 adições no fluxo do `/harness-evolve-init`:

```python
def init_project(harness_path, eval_path, tasks_path):
    # ... steps 1-6 existentes ...

    # NOVO Step 6.5: Detectar stack
    from detect_stack import detect_from_file
    stack = detect_from_file(harness_path)

    if stack:
        config["stack"] = {
            "detected": stack,
            "documentation_hint": "use context7",
            "auto_detected": True
        }
        print(f"\nStack detectada:")
        for lib_key, lib_info in stack.items():
            print(f"  ✓ {lib_info['display']}")

        # Verificar se Context7 está disponível
        if not check_context7_available():
            print(f"\n💡 Recomendação: instale o Context7 MCP server para que o")
            print(f"   proposer consulte documentação atualizada ao propor mudanças:\n")
            print(f"   claude mcp add context7 -- npx -y @upstash/context7-mcp@latest\n")
            print(f"   Sem Context7, o proposer usa knowledge do modelo (pode estar desatualizado).")
    else:
        config["stack"] = {"detected": {}, "auto_detected": True}
        print("\nNenhuma biblioteca conhecida detectada na stack.")

    # ... steps 7-8 existentes ...


def check_context7_available():
    """Verifica se o Context7 MCP está configurado no Claude Code."""
    # Checa ~/.claude/settings.json ou similar
    claude_settings_paths = [
        os.path.expanduser("~/.claude/settings.json"),
        os.path.expanduser("~/.claude.json"),
        ".claude/settings.json"
    ]
    for path in claude_settings_paths:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    settings = json.load(f)
                mcp_servers = settings.get("mcpServers", {})
                if "context7" in mcp_servers or "Context7" in mcp_servers:
                    return True
            except (json.JSONDecodeError, KeyError):
                pass
    return False
```

### proposer.md — mudanças (3 linhas)

Na Fase 3 (PROPOR), adicionar:

```markdown
## Fase 3: PROPOR (~10% do contexto)

- Escrever novo `harness.py` baseado no melhor candidato + correções
- Escrever `config.json` se parâmetros mudaram
- Preferir mudanças aditivas quando risco é alto

### Consulta de documentação (se Context7 disponível)

- Ler `config.json` campo `stack.detected` para saber quais bibliotecas o harness usa.
- ANTES de escrever código que usa uma biblioteca da stack detectada,
  usar a tool `resolve-library-id` com o `context7_id` do config e depois
  `get-library-docs` para buscar a documentação relevante à mudança.
- Se Context7 NÃO estiver disponível, prosseguir com knowledge do modelo
  mas anotar no `proposal.md`: "⚠ API não verificada contra docs atuais."
- NÃO consultar docs pra cada linha de código — só quando estiver propondo
  mudanças que envolvem APIs específicas (novos imports, novos métodos,
  novos parâmetros).
```

---

## 5. Fluxo completo com Context7

```
/harness-evolve-init --harness ./chatbot.py --eval ./eval.py --tasks ./tasks/

Stack detectada:
  ✓ LangChain
  ✓ LangGraph
  ✓ ChromaDB

💡 Recomendação: instale o Context7 MCP server:
   claude mcp add context7 -- npx -y @upstash/context7-mcp@latest

# Usuário instala Context7
$ claude mcp add context7 -- npx -y @upstash/context7-mcp@latest

# Roda o evolver
/harness-evolve --iterations 10

# Iteração 3 — o proposer diagnostica:
# "task_005 falhou porque o retriever retorna chunks irrelevantes.
#  O harness usa VectorStoreRetriever sem filtering."
#
# Proposer consulta Context7:
#   → resolve-library-id("langchain") → /langchain-ai/langchain
#   → get-library-docs("/langchain-ai/langchain", "contextual compression retriever")
#   → Recebe: docs atuais do ContextualCompressionRetriever com exemplo
#
# Proposer propõe:
# "Substituir VectorStoreRetriever por ContextualCompressionRetriever
#  com LLMChainExtractor. API verificada via Context7."
#
# proposal.md inclui:
# "Mudança: Added ContextualCompressionRetriever (verified via Context7 docs).
#  The compressor filters irrelevant chunks before passing to LLM."
```

---

## 6. O que o proposer pode salvar (opcional)

Pra referência futura, o proposer pode salvar os docs consultados no filesystem:

```
harnesses/v003/
├── harness.py
├── config.json
├── proposal.md
├── scores.json
├── traces/
└── docs_consulted/              # NOVO — opcional
    ├── langchain_compression_retriever.md
    └── chromadb_filtering.md
```

Isso serve dois propósitos:
1. O proposer futuro pode ler `docs_consulted/` de versões anteriores pra não reconsultar a mesma coisa
2. O usuário pode auditar quais docs foram usados pra cada proposta

O proposer decide se salva ou não baseado na relevância. Não é obrigatório.

---

## 7. Tratamento de edge cases

### Context7 não instalado

```
# proposer.md diz:
# "Se Context7 NÃO estiver disponível, prosseguir com knowledge do modelo
#  mas anotar no proposal.md: '⚠ API não verificada contra docs atuais.'"

# O loop continua normalmente. Zero impacto na funcionalidade.
```

### Biblioteca não indexada no Context7

```
# resolve-library-id retorna "not found"
# Proposer anota: "Biblioteca X não encontrada no Context7. Usando knowledge do modelo."
# Pode tentar web search como fallback (se disponível como MCP)
```

### Stack muda entre versões

O proposer pode adicionar imports novos (ex: v005 adiciona `import redis`). O `detect_stack.py` roda no baseline, não nas versões evoluídas. O proposer é inteligente o suficiente pra perceber que está usando uma biblioteca nova e consultar docs se necessário.

Opcionalmente, o `state.py` pode re-rodar `detect_stack.py` em cada nova versão e atualizar o `summary.json`:

```json
{
  "history": [
    {"version": "v001", "combined_score": 0.62, "parent": "baseline",
     "stack_additions": []},
    {"version": "v005", "combined_score": 0.87, "parent": "v003",
     "stack_additions": ["redis"]}
  ]
}
```

### Consultas excessivas ao Context7

Regra no proposer.md: "NÃO consultar docs pra cada linha de código — só quando estiver propondo mudanças que envolvem APIs específicas." Isso limita a 2-4 consultas por iteração, adicionando ~10-20s de latência. Aceitável.

---

## 8. Compatibilidade com outros MCP servers de documentação

O Context7 não é o único. O proposer pode usar qualquer MCP de docs:

| MCP Server | O que faz | Quando usar |
|---|---|---|
| **Context7** | Docs de bibliotecas open-source indexadas | Default — mais rápido, maior catálogo |
| **Web Search (Brave, Perplexity)** | Busca geral na web | Fallback quando Context7 não tem a lib |
| **Custom docs server** | Docs internas da empresa | Harnesses que usam libs proprietárias |
| **GitHub MCP** | Código-fonte e READMEs de repos | Quando precisa de implementação, não docs |

O `proposer.md` é agnóstico ao MCP específico. A instrução é "consulte documentação antes de escrever código novo" — o Claude Code decide qual tool usar baseado no que está disponível.

O `stack.documentation_hint` no config pode ser customizado:

```json
{
  "stack": {
    "documentation_hint": "use context7",
    "fallback_hint": "search the web for current documentation"
  }
}
```

---

## 9. Checklist de implementação

### Novos arquivos

| Arquivo | Descrição | Tamanho | Prioridade |
|---|---|---|---|
| `tools/detect_stack.py` | Detector de stack via AST (stdlib-only) | ~100 linhas | P0 da integração |

### Arquivos modificados

| Arquivo | Mudança | Escopo |
|---|---|---|
| `tools/init.py` | Chamar `detect_stack.py`, salvar `stack` no config, checar Context7, imprimir sugestão | Pequeno — ~30 linhas |
| `agents/harness-evolver-proposer.md` | Adicionar bloco "Consulta de documentação" na Fase 3 | Mínimo — ~10 linhas de markdown |
| `config.json` template | Adicionar seção `stack` | Mínimo |

### Nada muda

| Arquivo | Por quê |
|---|---|
| `evaluate.py` | Context7 não afeta avaliação — só a proposta |
| `state.py` | Stack é informação estática, não muda entre iterações (exceto re-detecção opcional) |
| `install.js` | Context7 é instalado pelo usuário separadamente via `claude mcp add` |
| `trace_logger.py` | Traces são sobre execução, não sobre documentação |
| Contrato do harness | --input, --output, --traces-dir, --config não mudam |
| Contrato do eval | --results-dir, --tasks-dir, --scores não mudam |
| Loop de evolução | O proposer consulta docs internamente, o loop não precisa saber |

---

## 10. Interação com LangSmith integration

Context7 e LangSmith são **completamente ortogonais**:

```
LangSmith = OBSERVABILIDADE (o que aconteceu? como avaliar?)
  → Enriquece traces e scores
  → Afeta: evaluate.py, scores.json, traces/

Context7 = CONHECIMENTO (como resolver corretamente?)
  → Enriquece as propostas do proposer
  → Afeta: proposer.md, proposal.md, docs_consulted/
```

Podem ser usados simultaneamente, separadamente, ou nenhum dos dois. A arquitetura é aditiva:

```
MVP alone:          traces + scores → proposer → harness
+ LangSmith:        traces RICOS + scores RICOS → proposer → harness
+ Context7:         traces + scores → proposer + DOCS → harness MELHOR
+ Ambos:            traces RICOS + scores RICOS → proposer + DOCS → harness MUITO MELHOR
```

---

## 11. Estimativa de esforço

| Task | Esforço | Depende de |
|---|---|---|
| Escrever `detect_stack.py` | 2 horas | Nada |
| Modificar `init.py` (detecção + sugestão) | 1 hora | detect_stack.py |
| Adicionar bloco no `proposer.md` | 30 min | Nada |
| Atualizar template do `config.json` | 15 min | Nada |
| Testar com harness LangGraph real | 1 hora | Tudo acima |
| **Total** | **~5 horas** | — |

Comparação: LangSmith integration = ~7 dias. Context7 integration = **meio dia**.

---

## 12. Roadmap

| Versão | Feature |
|---|---|
| **v0.4** | `detect_stack.py` + detecção no init + instrução no proposer |
| **v0.4** | `docs_consulted/` opcional no filesystem |
| **v0.5** | Re-detecção de stack em cada versão nova |
| **v0.5** | Suporte a custom docs MCP (libs internas) |
| **v0.6** | Cache de docs consultados (evitar re-fetch da mesma doc) |

---

## 13. Referências

- [1] Context7 Platform — github.com/upstash/context7
- [2] Context7 Claude Code Plugin — deepwiki.com/upstash/context7/9-claude-plugin
- [3] Context7 MCP Setup Guide — claudefa.st/blog/tools/mcp-extensions/context7-mcp
- [4] Claude Code MCP Docs — code.claude.com/docs/en/mcp
- [5] Context7 Claude Plugin (official) — claude.com/plugins/context7
- [6] Lee et al. "Meta-Harness: End-to-End Optimization of Model Harnesses." arxiv 2603.28052, 2026.
- [7] Harness Evolver Design Spec v0.1. 2026-03-31.
- [8] Harness Evolver × LangSmith Integration. 2026-03-31.
