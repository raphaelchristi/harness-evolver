# Architecture

For the quick overview, see [README.md](../README.md).

## System Overview

```mermaid
graph TB
    subgraph Plugin["Plugin Layer"]
        Hook["SessionStart Hook<br/><i>Creates venv, installs deps, exports env vars</i>"]
    end

    subgraph Skills["Skills Layer (Markdown)"]
        Setup["/evolver:setup"]
        Health["/evolver:health"]
        Evolve["/evolver:evolve"]
        Status["/evolver:status"]
        Deploy["/evolver:deploy"]
    end

    subgraph Agents["Agent Layer (Markdown)"]
        direction LR
        Proposer["Proposer (xN)<br/>🟢 Self-organizing"]
        Evaluator["Evaluator<br/>🟡 LLM-as-judge"]
        Critic["Critic<br/>🔴 Anti-gaming"]
        Architect["Architect<br/>🔵 ULTRAPLAN"]
        Consolidator["Consolidator<br/>🔵 Memory"]
        TestGen["TestGen<br/>🔵 Data gen"]
    end

    subgraph Tools["Tools Layer (Python)"]
        direction LR
        Core["setup.py<br/>run_eval.py<br/>read_results.py"]
        Analysis["trace_insights.py<br/>seed_from_traces.py<br/>dataset_health.py"]
        Safety["constraint_check.py<br/>secret_filter.py<br/>preflight.py"]
        History["archive.py<br/>regression_tracker.py<br/>evolution_chart.py"]
    end

    subgraph External["External"]
        LS["LangSmith<br/><i>Datasets · Experiments · Feedback</i>"]
        Git["Git Worktrees<br/><i>Isolated candidate code</i>"]
    end

    Hook --> Skills
    Evolve --> Agents
    Agents --> Tools
    Tools --> LS
    Proposer --> Git
    
    style Plugin fill:#1a1a2e,color:#fff
    style Skills fill:#16213e,color:#fff
    style Agents fill:#0f3460,color:#fff
    style Tools fill:#533483,color:#fff
    style External fill:#e94560,color:#fff
```

## Evolution Loop

```mermaid
flowchart TD
    Start(["/evolver:evolve"]) --> Preflight

    subgraph Pre["Pre-Loop"]
        Preflight["1. Preflight<br/><i>API key + schema + state + health + canary</i>"]
        Baseline["Baseline LLM-judge<br/><i>Re-score if only has_output</i>"]
        Preflight --> Baseline
    end

    Baseline --> Loop

    subgraph Loop["Per Iteration"]
        Analyze["2. Analyze<br/><i>trace_insights + read_results (--format summary)</i>"]
        Strategy["Strategy + Lenses<br/><i>strategy.md (1500 tok cap) + lenses.json</i>"]
        
        subgraph Propose["3. Propose"]
            Wave1["Wave 1<br/><i>Critical/high lenses</i>"]
            Wave2["Wave 2<br/><i>Medium/open (sees wave 1)</i>"]
            Wave1 --> Wave2
        end
        
        Eval["4. Evaluate<br/><i>Canary → run_eval (rate-limit abort) → auto-spawn LLM-as-judge</i>"]
        
        subgraph Select["5. Select"]
            Compare["Compare on held-out"]
            Pairwise{"Top 2<br/>within 5%?"}
            PW["Pairwise comparison"]
            Constraint["Constraint gate"]
            Merge["Merge winner"]
            Compare --> Pairwise
            Pairwise -->|Yes| PW --> Constraint
            Pairwise -->|No| Efficiency
            Efficiency["Efficiency gate<br/><i>tokens 2x? latency 50%?</i>"]
            Efficiency -->|Pass| Constraint
            Efficiency -->|Fail| NextBest
            Constraint -->|Pass| Merge
            Constraint -->|Fail| NextBest["Try next-best"]
            NextBest --> Constraint
        end
        
        subgraph PostIter["6. Learn"]
            Archive["Archive ALL candidates"]
            Regression["Regression guards<br/><i>train-only, deduplicated</i>"]
            Memory["Consolidator<br/><i>background</i>"]
            Archive --> Regression --> Memory
        end

        Analyze --> Strategy --> Propose --> Eval --> Select --> PostIter
    end

    subgraph Gate["7. Gate (multi-objective)"]
        Check{"Continue?"}
        Plateau["Score plateau?"]
        Target["Target reached?"]
        Diminish["Diminishing returns?"]
        Cost["Cost regression?<br/><i>tokens 2x+, score &lt;2%</i>"]
        Latency["Latency regression?<br/><i>latency 50%+, score &lt;5%</i>"]
        Check --> Plateau & Target & Diminish & Cost & Latency
    end

    PostIter --> Gate
    Check -->|Yes| Loop
    Check -->|No| Report

    subgraph Auto["Auto-Triggers"]
        CriticTrigger["Critic<br/><i>if score jump >0.3</i>"]
        ArchTrigger["Architect<br/><i>if 3 iterations stagnated</i>"]
    end

    PostIter -.-> Auto

    Report(["Evolution Chart + Final Report"])
    
    style Pre fill:#1a1a2e,color:#fff
    style Loop fill:#16213e,color:#fff
    style Propose fill:#0f3460,color:#fff
    style Select fill:#533483,color:#fff
    style PostIter fill:#1a1a2e,color:#fff
    style Gate fill:#e94560,color:#fff
    style Auto fill:#0f3460,color:#fff
```

## Data Flow

```mermaid
flowchart LR
    subgraph Input["Data Sources"]
        TestFile["test_inputs.json"]
        ProdTraces["Production traces"]
        Sessions["Claude Code sessions"]
        Archive["evolution_archive/"]
    end

    subgraph Process["Processing"]
        Dataset["LangSmith Dataset<br/><i>train / held_out splits</i>"]
        Insights["trace_insights.json<br/><i>--format summary</i>"]
        Results["best_results.json<br/><i>--format summary</i>"]
        StrategyDoc["strategy.md<br/><i>1500 token cap</i>"]
        Lenses["lenses.json"]
    end

    subgraph Output["Evolution Output"]
        Config[".evolver.json<br/><i>enriched history</i>"]
        Chart["evolution_chart.py<br/><i>ASCII visualization</i>"]
        MemoryDoc["evolution_memory.md<br/><i>anchored insights</i>"]
        ArchiveOut["evolution_archive/<br/><i>all candidates</i>"]
    end

    TestFile --> Dataset
    ProdTraces --> Dataset
    Sessions --> Dataset
    Dataset --> Insights & Results
    Insights & Results --> StrategyDoc & Lenses
    Archive --> Lenses
    Lenses --> Config & ArchiveOut
    Config --> Chart
    Config --> MemoryDoc
    
    style Input fill:#1a1a2e,color:#fff
    style Process fill:#533483,color:#fff
    style Output fill:#e94560,color:#fff
```

## Tool Categories

```mermaid
graph LR
    subgraph Core["Core Pipeline"]
        setup["setup.py"]
        runeval["run_eval.py"]
        readresults["read_results.py"]
    end

    subgraph Analysis["Analysis"]
        trace["trace_insights.py"]
        seed["seed_from_traces.py"]
        mine["mine_sessions.py"]
    end

    subgraph Safety["Safety & Validation"]
        constraint["constraint_check.py"]
        secret["secret_filter.py"]
        preflight["preflight.py"]
        validate["validate_state.py"]
        health["dataset_health.py"]
    end

    subgraph Evolution["Evolution History"]
        archive["archive.py"]
        regression["regression_tracker.py"]
        chart["evolution_chart.py"]
        addev["add_evaluator.py"]
        adversarial["adversarial_inject.py"]
    end

    subgraph Shared["Shared"]
        common["_common.py"]
    end

    common -.-> Core & Analysis & Safety & Evolution

    style Core fill:#16213e,color:#fff
    style Analysis fill:#0f3460,color:#fff
    style Safety fill:#533483,color:#fff
    style Evolution fill:#e94560,color:#fff
    style Shared fill:#1a1a2e,color:#fff
```

## Entry Point Placeholders

| Placeholder | Behavior | Use when |
|---|---|---|
| `{input_text}` | Extracts plain text, shell-escapes it | Agent takes `--query "text"` or positional args |
| `{input}` | Passes path to a JSON file | Agent reads structured JSON from file |
| `{input_json}` | Passes raw JSON string inline | Agent parses JSON from command line |

```bash
python agent.py --query {input_text}   # text input
python agent.py {input}                # JSON file path
```
