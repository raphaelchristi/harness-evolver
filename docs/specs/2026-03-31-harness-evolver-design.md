# Harness Evolver — Design Spec v0.1

> **Autor**: Raphael Valdetaro Christi Cordeiro
> **Data**: 2026-03-31
> **Status**: Aprovado
> **Approach**: MVP Mínimo Funcional (Approach A)

## Resumo

Plugin para Claude Code que implementa o loop de otimização do Meta-Harness (Lee et al., 2026) como produto portável. Busca autônoma em code-space com filesystem completo + traces como feedback.

**Decisões de escopo (MVP):**
- Domain-agnostic: harness e eval são qualquer executável
- Proposer autônomo (subagent, sem checkpoints interativos)
- 3 skills: `init`, `evolve`, `status`
- 1 agent: `proposer`
- 4 tools Python stdlib-only
- 1 exemplo (classificador)
- Distribuição via `npx harness-evolver@latest` (Claude Code only no MVP)

---

## 1. Contrato do Harness e Eval

### Harness — qualquer executável

```bash
python3 harness.py --input task.json --output result.json --traces-dir traces/ --config config.json
```

- `--input`: JSON com `{id, input, metadata}` (sem expected — o harness nunca vê a resposta certa)
- `--output`: JSON com `{id, output, metadata}`
- `--traces-dir` (opcional): diretório onde o harness pode escrever traces extras
- `--config` (opcional): JSON com parâmetros evolvable (API keys, model, temperature)

### Eval — qualquer executável

```bash
python3 eval.py --results-dir results/ --tasks-dir tasks/ --scores scores.json
```

- `--results-dir`: diretório com outputs do harness
- `--tasks-dir`: diretório com tasks completas (inclui expected)
- `--scores`: path onde escrever o JSON de scores

### scores.json

```json
{
  "combined_score": 0.85,
  "accuracy": 0.90,
  "latency_avg_ms": 230,
  "per_task": {
    "task_001": {"score": 1.0},
    "task_002": {"score": 0.0, "error": "wrong category"}
  }
}
```

### Tasks

Cada task é um JSON em `eval/tasks/`:

```json
{"id": "task_001", "input": "Classify this text: ...", "expected": "category_A", "metadata": {}}
```

O `evaluate.py` (nosso tool) extrai `{id, input, metadata}` e passa pro harness. O harness nunca vê `expected`.

### Tratamento de falhas

- **Timeout**: configurável em `config.json` (default: 60s por task). Timeout → score 0.0 + trace.
- **Crash**: score 0.0 + stderr salvo no trace.
- **Output malformado**: score 0.0 + output bruto salvo pro proposer diagnosticar.

### Fluxo do evaluate.py

```
1. Lê tasks/*.json
2. Para cada task: extrai {id, input, metadata}, salva como input temporário
3. Chama: harness --input tmp_input.json --output result.json --traces-dir traces/ --config config.json
4. Captura stdout/stderr/timing
5. Depois de rodar todos os tasks: chama eval.py do usuário
6. eval.py compara results/ com tasks/ (que tem expected) → scores.json
```

---

## 2. Estrutura do Filesystem

```
.harness-evolver/
├── config.json                    # Config do projeto
├── STATE.md                       # Human-readable (view gerada)
├── summary.json                   # Machine-readable (source of truth)
├── PROPOSER_HISTORY.md            # Log consolidado de todas as propostas
│
├── baseline/                      # Harness original do usuário (read-only)
│   ├── harness.py
│   └── config.json
│
├── eval/
│   ├── eval.py                    # Script de avaliação do usuário
│   └── tasks/
│       ├── task_001.json
│       ├── task_002.json
│       └── ...
│
├── tools/                         # Python stdlib-only (copiados pelo installer)
│   ├── evaluate.py                # Orquestrador de avaliação
│   ├── state.py                   # Lê/escreve STATE.md, summary.json, PROPOSER_HISTORY.md
│   ├── init.py                    # Cria esta estrutura
│   └── trace_logger.py            # Helper opcional pro harness
│
└── harnesses/
    ├── v001/
    │   ├── harness.py             # Código do candidato
    │   ├── config.json            # Parâmetros evolvable
    │   ├── proposal.md            # Raciocínio do proposer
    │   ├── scores.json            # Resultado do eval
    │   └── traces/
    │       ├── stdout.log         # stdout completo
    │       ├── stderr.log         # stderr completo
    │       ├── timing.json        # Timing total e por task
    │       ├── task_001/
    │       │   ├── input.json     # O que o harness recebeu (sem expected)
    │       │   ├── output.json    # O que o harness retornou
    │       │   └── extra/         # Traces opcionais escritos pelo harness
    │       └── task_002/
    │           └── ...
    ├── v002/
    │   └── ...
    └── ...
```

### Decisões de design

1. **`baseline/` é read-only** — referência imutável. v001 é a primeira mutação.
2. **`proposal.md` obrigatório** — proposer documenta raciocínio. Serve auditoria e memória.
3. **Traces por task** — habilita diagnóstico contrafactual cross-version.
4. **`config.json` por versão** — proposer pode evoluir parâmetros além do código.
5. **Sem Pareto frontier explícita** — fiel ao Meta-Harness. Proposer inspeciona qualquer versão livremente.
6. **`summary.json` é o source of truth** — `STATE.md` é view gerada, `state.py` atualiza ambos.
7. **`PROPOSER_HISTORY.md`** — log consolidado que previne repetição de erros.

### summary.json

```json
{
  "iterations": 7,
  "best": {"version": "v005", "combined_score": 0.87},
  "worst": {"version": "v002", "combined_score": 0.31},
  "history": [
    {"version": "v001", "combined_score": 0.62, "parent": "baseline"},
    {"version": "v002", "combined_score": 0.31, "parent": "v001"},
    {"version": "v003", "combined_score": 0.71, "parent": "v001"},
    {"version": "v005", "combined_score": 0.87, "parent": "v003"}
  ]
}
```

**Como o `parent` é determinado:** o proposer declara o parent no `proposal.md` (ex: "Based on v003"). O `state.py` parseia isso ao atualizar o `summary.json`. Se não encontrar declaração explícita, assume o melhor candidato atual como parent. Isso dá ao proposer liberdade pra fazer saltos (basear v007 no v003 em vez do v006).

### PROPOSER_HISTORY.md

```markdown
## v001 (score: 0.62)
Baseline mutation. Added retry logic for API timeouts.

## v002 (score: 0.31) <- REGRESSION
Tried to change prompt template. Broke JSON parsing in 4/10 tasks.

## v003 (score: 0.71)
Reverted v002 prompt changes, kept v001 retry logic. Added output validation.
```

---

## 3. O Proposer Agent

Subagent do Claude Code. Coração do sistema — equivalente do "coding agent as proposer" do Meta-Harness.

### Contrato

- **Entrada**: filesystem `.harness-evolver/` completo + número da iteração
- **Saída**: `harnesses/v{N}/` com `harness.py`, `config.json`, `proposal.md` + append em `PROPOSER_HISTORY.md`
- **Acesso**: irrestrito a `grep`, `cat`, `diff`, `find` no diretório

### Workflow (4 fases)

**Fase 1: ORIENTAR (~6% do contexto)**
- Ler `summary.json` — panorama de scores e linhagem
- Ler `PROPOSER_HISTORY.md` — decisões anteriores, o que funcionou, o que regrediu
- Decidir: em quais versões focar?

**Fase 2: DIAGNOSTICAR (~80% do contexto)**
- Selecionar no máximo 3 versões pra diagnóstico profundo:
  - (a) o melhor candidato atual
  - (b) a regressão mais recente
  - (c) uma versão com failure mode diferente
- Ler traces dessas versões. Não ler traces de todas as versões.
- grep por erros, padrões de falha
- diff entre harness de versão boa vs ruim
- Diagnóstico contrafactual: "task_003 falhou em v005 mas passou em v003 — o que mudou?"
- Identificar 1-3 failure modes específicos

**Fase 3: PROPOR (~10% do contexto)**
- Escrever novo `harness.py` baseado no melhor candidato + correções
- Escrever `config.json` se parâmetros mudaram
- Preferir mudanças aditivas quando risco é alto (padrão do paper)

**Fase 4: DOCUMENTAR (~4% do contexto)**
- Escrever `proposal.md` com raciocínio completo
- Append em `PROPOSER_HISTORY.md`

### Regras do proposer

1. **Toda mudança motivada por evidência** — nunca mudar "pra ver o que acontece". Citar task ID, trace line, ou score delta.
2. **Após regressão, preferir mudanças aditivas** — o paper mostra que o proposer aprende a ser mais conservador após regressions.
3. **Não repetir erros** — ler `PROPOSER_HISTORY.md` antes de propor. Se uma abordagem já falhou, não tentar variante similar sem justificativa.
4. **Uma hipótese por vez quando possível** — mudanças confounded (A+B+C simultâneo) dificultam diagnóstico na próxima iteração.
5. **O harness deve manter a interface** — `--input`, `--output`, `--traces-dir`, `--config` devem continuar funcionando.
6. **Preferir harnesses legíveis a harnesses defensivos** — se o harness cresce sem ganho proporcional de score, considerar simplificar. Heurística: se `harness.py` ultrapassar 2x o tamanho do baseline sem ganho correspondente, anotar no `proposal.md` e considerar refactor.

### O que o proposer NÃO faz

- Não roda o eval (o skill `evolve.md` faz isso depois)
- Não modifica `eval/` (eval set é fixo)
- Não modifica `baseline/` (referência read-only)
- Não modifica versões anteriores (histórico é imutável)

---

## 4. O Loop de Evolução (skill `evolve.md`)

### Invocação

```
/harness-evolve --iterations 10 --candidates-per-iter 1
```

### Parâmetros

- `--iterations` (default: 10)
- `--candidates-per-iter` (default: 1)

### O loop

```
para cada iteração i de 1 até N:

  1. PROPOR
     -> Disparar proposer agent
     -> Input: .harness-evolver/ inteiro
     -> Output: harnesses/v{i}/ com harness.py, config.json, proposal.md

  2. VALIDAR
     -> python3 tools/evaluate.py validate --harness harnesses/v{i}/harness.py
     -> Verifica: arquivo existe, CLI flags funcionam, output é JSON válido
     -> Se falha: proposer tenta corrigir (1 retry). Se falha de novo: score 0.0, segue.

  3. AVALIAR
     -> python3 tools/evaluate.py run \
         --harness harnesses/v{i}/harness.py \
         --config harnesses/v{i}/config.json \
         --tasks-dir eval/tasks/ \
         --eval eval/eval.py \
         --traces-dir harnesses/v{i}/traces/ \
         --scores harnesses/v{i}/scores.json \
         --timeout 60

  4. ATUALIZAR ESTADO
     -> python3 tools/state.py update \
         --version v{i} \
         --scores harnesses/v{i}/scores.json
     -> Atualiza: summary.json, STATE.md, PROPOSER_HISTORY.md

  5. REPORTAR
     -> "Iteracao {i}: v{i} scored {score} (best: v{best} at {best_score})"
     -> Se regressao: "Regressao: {score} < {parent_score}"
     -> Se novo melhor: "Novo melhor: {score}"
```

### Condições de parada

- **N atingido**: para normalmente
- **Estagnação**: 3 iterações consecutivas sem melhoria > 1%
- **Target atingido**: se `config.json` define `target_score` e é atingido

---

## 5. Config e Init

### config.json (raiz)

```json
{
  "version": "0.1.0",
  "harness": {
    "command": "python3 harness.py",
    "args": ["--input", "{input}", "--output", "{output}", "--traces-dir", "{traces_dir}", "--config", "{config}"],
    "timeout_per_task_sec": 60
  },
  "eval": {
    "command": "python3 eval.py",
    "args": ["--results-dir", "{results_dir}", "--tasks-dir", "{tasks_dir}", "--scores", "{scores}"]
  },
  "evolution": {
    "max_iterations": 10,
    "candidates_per_iter": 1,
    "stagnation_limit": 3,
    "stagnation_threshold": 0.01,
    "target_score": null
  },
  "paths": {
    "baseline": "baseline/",
    "eval_tasks": "eval/tasks/",
    "eval_script": "eval/eval.py",
    "harnesses": "harnesses/"
  }
}
```

Placeholders `{input}`, `{output}`, `{traces_dir}`, `{config}` substituídos pelo `evaluate.py` em runtime.

### Skill `/harness-evolve-init`

```
/harness-evolve-init --harness ./my_harness.py --eval ./my_eval.py --tasks ./test_cases/
```

Passos:
1. Cria `.harness-evolver/` com toda a estrutura
2. Copia harness para `baseline/harness.py`
3. Copia eval para `eval/eval.py`
4. Copia tasks para `eval/tasks/`
5. Copia tools Python para `tools/`
6. Gera `config.json` com defaults
7. Roda `evaluate.py validate` pra confirmar que tudo funciona
8. Roda eval no baseline e salva score em `summary.json` como ponto de partida

---

## 6. Installer e Distribuição

### Pacote npm

```json
{
  "name": "harness-evolver",
  "version": "0.1.0",
  "bin": {
    "harness-evolver": "bin/install.js"
  }
}
```

### Invocação

```bash
npx harness-evolver@latest
```

### O que o install.js faz

1. Detecta runtime (MVP: só Claude Code, verifica `~/.claude/`)
2. Copia skills para `~/.claude/commands/harness-evolver/`
3. Copia agent para `~/.claude/agents/`
4. Armazena tools Python em `~/.harness-evolver/tools/` (global)
5. Verifica que `python3` existe no PATH
6. Mensagem: `Installed. Run /harness-evolve-init in your project to start.`

### Tools: global com override local

Tools Python ficam em `~/.harness-evolver/tools/` (global). Se o usuário copiar pra `.harness-evolver/tools/` do projeto, a cópia local tem prioridade.

### Fora do MVP

- Detecção de Codex, Gemini CLI, Cursor
- Self-update
- Uninstall

---

## 7. Exemplo: Classificador

### Estrutura

```
examples/classifier/
├── README.md
├── harness.py         # Classificador naive (sem few-shot, sem retry, prompt genérico)
├── eval.py            # Exact match accuracy
└── tasks/
    ├── task_001.json  # {"id": "task_001", "input": "The patient has fever and cough", "expected": "respiratory"}
    ├── task_002.json
    └── ... (10 tasks)
```

### harness.py

Classificador deliberadamente ingênuo com espaço óbvio pra melhoria:
- Sem few-shot examples
- Sem structured output
- Sem retry
- Prompt genérico

Suporta `--mock` (ou via `config.json` `{"mock": true}`) para rodar com keyword matching em vez de LLM. Permite testar o loop end-to-end sem API key e sem custo. Mock começa com ~40% accuracy; LLM real começa com ~50-60%.

Dois cenários de uso:
- **Primeiro contato**: roda com mock, vê o loop funcionar em 30 segundos, zero dependências externas.
- **Teste real**: configura API key no `config.json`, roda com LLM real, melhorias dramáticas (few-shot, structured output, etc.).

### eval.py

Exact match accuracy: compara `output.lower().strip()` com `expected.lower().strip()`.

### Curva de melhoria esperada

- Iteração 1-2: Few-shot examples no prompt -> +15-20%
- Iteração 3-4: Structured output / constrained categories -> +10%
- Iteração 5-6: Retry com reformulação -> +5%
- Iteração 7+: Edge cases, prompt refinement -> +2-3%

---

## Resumo de Artefatos a Implementar

| Artefato | Tipo | Prioridade |
|---|---|---|
| `bin/install.js` | Node.js | P0 |
| `package.json` | npm config | P0 |
| `skills/harness-evolve-init/SKILL.md` | Skill markdown | P0 |
| `skills/harness-evolve/SKILL.md` | Skill markdown | P0 |
| `skills/harness-evolve-status/SKILL.md` | Skill markdown | P0 |
| `agents/harness-evolver-proposer.md` | Agent markdown | P0 |
| `tools/init.py` | Python stdlib | P0 |
| `tools/evaluate.py` | Python stdlib | P0 |
| `tools/state.py` | Python stdlib | P0 |
| `tools/trace_logger.py` | Python stdlib | P0 |
| `examples/classifier/harness.py` | Python | P0 |
| `examples/classifier/eval.py` | Python | P0 |
| `examples/classifier/tasks/*.json` | JSON | P0 |

---

## Referências

- [1] Lee et al. "Meta-Harness: End-to-End Optimization of Model Harnesses." arxiv 2603.28052, 2026.
- [2] GSD "Get Shit Done." github.com/gsd-build/get-shit-done
- [3] Harbor. github.com/laude-institute/harbor
- [4] OpenEvolve. github.com/algorithmicsuperintelligence/openevolve
- [5] A-Evolve. github.com/A-EVO-Lab/a-evolve
