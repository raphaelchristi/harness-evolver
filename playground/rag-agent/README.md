# RAG Agent — NovaTech Knowledge Base

RAG agent that answers questions about a fictional company (NovaTech Solutions) using a 12-document knowledge base. Uses keyword-matching retrieval (deliberately bad). Gemini 2.0 Flash Lite.

## Why it's bad

- **Keyword retrieval**: Counts word overlap instead of semantic similarity. "How much does it cost?" won't match the pricing doc because "cost" doesn't appear in it — "pricing" does
- **No reranking**: Returns top-2 docs by word overlap, even if neither is relevant
- **Context stuffing**: Dumps retrieved docs into the prompt without checking relevance
- **Only retrieves 2 docs**: Some questions need info from multiple docs (e.g., pricing + features)
- **No fallback**: When retrieval fails, the LLM either hallucinates or says "I don't know" even though the answer exists in the knowledge base

## Expected scores

- **Baseline**: ~40-45% (wrong docs retrieved, missing answers, hallucination on retrieval miss)
- **Target after evolution**: ~75-85% (semantic search, better retrieval, reranking)

## Evolution vectors

1. Replace keyword matching with embedding-based retrieval (ChromaDB)
2. Increase top_k from 2 to 3-4
3. Add relevance scoring / reranking
4. Better system prompt (cite sources, admit uncertainty)
5. Retrieve all docs for broad questions

## Architecture

```
Query → Keyword Retrieval → Context Stuffing → LLM → Answer
```

Topology: **RAG** (retrieval-augmented generation). The architect should detect this and suggest embedding-based retrieval.

## Knowledge base

12 documents about NovaTech Solutions covering: company overview, products (Atlas, Beacon), pricing, tech stack, security, team, roadmap, competitors, case study, API, and support policy.

## Setup

```bash
export GOOGLE_API_KEY="your-key"
export LANGSMITH_API_KEY="your-key"
export LANGSMITH_TRACING=true

cd playground/rag-agent
pip install -r ../requirements.txt
python agent.py test_inputs.json
```
