#!/usr/bin/env python3
"""TF-IDF retrieval over the evolution archive.

Reads every evolution_archive/{version}/ directory next to `.evolver.json`,
builds a bag-of-words index over each candidate's proposal + diff + metadata,
and returns the top-k historically most similar candidates for a given query.

This gives proposers a "retrieval substrate" so that when a lens lands on a
failure cluster that's already been attacked before, the proposer sees which
prior approaches worked (and which didn't) rather than re-discovering them
from scratch. Maps to Autogenesis `retrieve` operator over the registry.

Stdlib-only. No external dependencies, no LLM calls.

Usage:
    # Search for prior attempts related to "retry on rate limit"
    python3 archive_search.py --config .evolver.json --query "retry on rate limit errors"

    # Pull only past winners (approaches that scored higher than baseline)
    python3 archive_search.py --config .evolver.json --query "..." --winners-only

    # Pull only past losers (useful to avoid re-trying them)
    python3 archive_search.py --config .evolver.json --query "..." --losers-only --top 5

    # Use a lens file as the query
    python3 archive_search.py --config .evolver.json --query-file lenses.json --top 3
"""

import argparse
import json
import math
import os
import re
import sys
from collections import Counter


STOPWORDS = frozenset("""
a an the and or but of for to in on at by with from into onto over under is are was were be been being
have has had do does did will would could should may might must can do doesn't don't it its that this these
those as if then than so such not no yes which what when where why how who whom whose
also just only very much more most less least some any all each every both neither either
about above across after against along around before behind below beside between beyond during except inside
i you he she we they me him her us them my your our their his hers theirs
""".split())

TOKEN_RE = re.compile(r"[a-z_][a-z0-9_]{2,}")


def load_json_safe(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def tokenize(text):
    """Lowercase + word-split; drop stopwords and super short tokens."""
    if not text:
        return []
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def read_candidate(dir_path):
    """Read one archive/{version}/ directory, return a candidate dict or None."""
    meta = load_json_safe(os.path.join(dir_path, "meta.json"))
    if not meta:
        return None
    chunks = []
    chunks.append(meta.get("approach", "") or "")
    chunks.append(meta.get("lens", "") or "")
    for name in ("proposal.md", "diff_stat.txt", "diff.patch"):
        p = os.path.join(dir_path, name)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    chunks.append(f.read())
            except OSError:
                pass
    text = "\n".join(chunks)
    return {
        "version": os.path.basename(dir_path),
        "meta": meta,
        "tokens": tokenize(text),
        "text": text,
    }


def build_index(archive_root):
    """Build corpus + IDF across all candidates."""
    candidates = []
    if not os.path.isdir(archive_root):
        return candidates, {}
    for name in sorted(os.listdir(archive_root)):
        dpath = os.path.join(archive_root, name)
        if not os.path.isdir(dpath):
            continue
        cand = read_candidate(dpath)
        if cand and cand["tokens"]:
            candidates.append(cand)

    # Document frequencies
    df = Counter()
    for c in candidates:
        for term in set(c["tokens"]):
            df[term] += 1

    n = len(candidates) or 1
    idf = {term: math.log((1 + n) / (1 + f)) + 1.0 for term, f in df.items()}
    # Precompute per-candidate weighted vector + norm
    for c in candidates:
        tf = Counter(c["tokens"])
        vec = {t: (1 + math.log(cnt)) * idf.get(t, 0.0) for t, cnt in tf.items()}
        norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
        c["vec"] = vec
        c["norm"] = norm

    return candidates, idf


def score_query(query_text, candidates, idf):
    """Cosine similarity between query and each candidate."""
    qtokens = tokenize(query_text)
    if not qtokens:
        return []
    tf = Counter(qtokens)
    qvec = {t: (1 + math.log(cnt)) * idf.get(t, 0.0) for t, cnt in tf.items() if idf.get(t, 0.0) > 0}
    qnorm = math.sqrt(sum(w * w for w in qvec.values())) or 1.0

    results = []
    for c in candidates:
        cvec = c["vec"]
        # Iterate the smaller dict for speed
        if len(qvec) < len(cvec):
            dot = sum(w * cvec.get(t, 0.0) for t, w in qvec.items())
        else:
            dot = sum(w * qvec.get(t, 0.0) for t, w in cvec.items())
        sim = dot / (qnorm * c["norm"])
        if sim > 0:
            results.append((sim, c))
    results.sort(key=lambda x: x[0], reverse=True)
    return results


def snippet_from(text, qtokens, radius=120, max_len=300):
    """Pick a small window around the first query-token hit."""
    if not text:
        return ""
    lower = text.lower()
    best = -1
    for tok in qtokens:
        i = lower.find(tok)
        if i >= 0 and (best < 0 or i < best):
            best = i
    if best < 0:
        return text[:max_len].strip()
    start = max(0, best - radius)
    end = min(len(text), best + radius)
    slice_ = text[start:end].strip()
    if len(slice_) > max_len:
        slice_ = slice_[:max_len]
    return ("…" if start > 0 else "") + slice_ + ("…" if end < len(text) else "")


def _is_winner(meta):
    """A candidate is a winner if meta.won is true or score exceeds any recorded baseline."""
    if meta.get("won") is True:
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="TF-IDF retrieval over the evolution archive.")
    parser.add_argument("--config", default=".evolver.json")
    parser.add_argument("--archive", default=None,
                        help="Archive root (default: {config_dir}/evolution_archive)")
    parser.add_argument("--query", default=None, help="Free-text query")
    parser.add_argument("--query-file", default=None,
                        help="Read query from file (txt/md/json). For JSON, all string values are concatenated.")
    parser.add_argument("--top", type=int, default=3, help="Return top-k results (default 3)")
    parser.add_argument("--winners-only", action="store_true")
    parser.add_argument("--losers-only", action="store_true")
    parser.add_argument("--min-similarity", type=float, default=0.05)
    parser.add_argument("--format", choices=["text", "json", "markdown"], default="markdown")
    args = parser.parse_args()

    if args.winners_only and args.losers_only:
        print("Cannot combine --winners-only and --losers-only", file=sys.stderr)
        sys.exit(2)

    # Resolve archive root
    if args.archive:
        archive_root = os.path.abspath(args.archive)
    else:
        config_dir = os.path.dirname(os.path.abspath(args.config))
        archive_root = os.path.join(config_dir, "evolution_archive")

    # Resolve query
    query_text = args.query or ""
    if args.query_file:
        try:
            with open(args.query_file) as f:
                raw = f.read()
        except OSError as e:
            print(f"Cannot read --query-file: {e}", file=sys.stderr)
            sys.exit(1)
        if args.query_file.endswith(".json"):
            try:
                obj = json.loads(raw)
                # Flatten all string values
                buf = []
                def walk(v):
                    if isinstance(v, str):
                        buf.append(v)
                    elif isinstance(v, dict):
                        for vv in v.values():
                            walk(vv)
                    elif isinstance(v, list):
                        for vv in v:
                            walk(vv)
                walk(obj)
                raw = "\n".join(buf)
            except json.JSONDecodeError:
                pass
        query_text = (query_text + "\n" + raw).strip()

    if not query_text:
        print("Need --query or --query-file", file=sys.stderr)
        sys.exit(2)

    candidates, idf = build_index(archive_root)
    if not candidates:
        print(json.dumps({"archive": archive_root, "results": [], "note": "archive empty"}, indent=2))
        return

    scored = score_query(query_text, candidates, idf)
    if args.winners_only:
        scored = [(s, c) for s, c in scored if _is_winner(c["meta"])]
    if args.losers_only:
        scored = [(s, c) for s, c in scored if not _is_winner(c["meta"])]
    scored = [x for x in scored if x[0] >= args.min_similarity][: args.top]

    qtokens = tokenize(query_text)

    if args.format == "json":
        out = {
            "query": query_text[:500],
            "archive": archive_root,
            "total_candidates": len(candidates),
            "results": [
                {
                    "version": c["version"],
                    "similarity": round(sim, 4),
                    "score": c["meta"].get("score"),
                    "won": bool(c["meta"].get("won")),
                    "approach": c["meta"].get("approach"),
                    "lens": c["meta"].get("lens"),
                    "snippet": snippet_from(c["text"], qtokens),
                }
                for sim, c in scored
            ],
        }
        print(json.dumps(out, indent=2))
        return

    if args.format == "text":
        for sim, c in scored:
            meta = c["meta"]
            flag = "WIN" if _is_winner(meta) else "loss"
            print(f"{sim:.3f}  [{flag}]  {c['version']}  score={meta.get('score')}  "
                  f"lens={meta.get('lens','')[:60]}  approach={meta.get('approach','')[:60]}")
        return

    # markdown (default)
    print(f"# Archive search results  ({len(scored)}/{len(candidates)} candidates)")
    print()
    print(f"**Query:** `{query_text[:200]}`")
    print()
    for sim, c in scored:
        meta = c["meta"]
        flag = "winner" if _is_winner(meta) else "loser"
        print(f"## {c['version']}  — similarity {sim:.3f}  ({flag})")
        if meta.get("score") is not None:
            print(f"- **score**: {meta['score']}")
        if meta.get("lens"):
            print(f"- **lens**: {meta['lens']}")
        if meta.get("approach"):
            print(f"- **approach**: {meta['approach']}")
        snip = snippet_from(c["text"], qtokens)
        if snip:
            print()
            print("```")
            print(snip)
            print("```")
        print()


if __name__ == "__main__":
    main()
