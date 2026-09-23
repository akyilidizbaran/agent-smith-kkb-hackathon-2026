"""Reproducible BM25 / MIA dense / RRF diagnostic, with query-level rankings.

No threshold tuning. Unknown/ambiguous/adversarial queries are withheld from IR
accuracy and saved for separate abstention evaluation. Does not test an agent.
"""
import json
import hashlib
import math
import re
import statistics
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/calisma-notlari/research_audit'


def tokens(s):
    s = s.translate(str.maketrans('Iİı', 'iii')).casefold()
    return re.findall(r'\w+', s, re.UNICODE)


def metrics(ranking, relevant):
    truth = set(relevant)
    scores = {}
    for k in [1, 3, 5]:
        hits = len(set(ranking[:k]) & truth)
        scores[f'recall@{k}'] = hits / len(truth)
        scores[f'precision@{k}'] = hits / k
    scores['mrr'] = next((1/i for i, x in enumerate(ranking, 1) if x in truth), 0)
    dcg = sum((x in truth) / math.log2(i+1) for i, x in enumerate(ranking[:5], 1))
    ideal = sum(1/math.log2(i+1) for i in range(1, min(5, len(truth))+1))
    scores['ndcg@5'] = dcg/ideal
    return scores


def main():
    fixture = json.loads((ROOT / 'tests/benchmark/retrieval_audit_fixture.json').read_text(encoding='utf-8'))
    docs, queries = fixture['documents'], fixture['queries']
    corpus = [Counter(tokens(x['text'])) for x in docs]
    n = len(docs)
    lengths = [sum(x.values()) for x in corpus]
    avgdl = statistics.mean(lengths)
    df = Counter(t for d in corpus for t in d)
    vectors_path = OUT / 'synthetic_embeddings.json'
    artifact = json.loads(vectors_path.read_text()) if vectors_path.exists() else None
    if artifact:
        assert artifact['fixture_sha256'] == hashlib.sha256((ROOT / 'tests/benchmark/retrieval_audit_fixture.json').read_bytes()).hexdigest(), 'Stale embeddings'
    vectors = artifact['vectors'] if artifact else None
    if vectors is not None:
        assert len(vectors) == len(docs) + len(queries), 'Wrong embedding fixture'
        assert len({len(v) for v in vectors}) == 1 and all(all(math.isfinite(x) for x in v) for v in vectors)
        vectors = [[x / math.sqrt(sum(t*t for t in v)) for x in v] for v in vectors]
    details = []
    for qi, q in enumerate(queries):
        start = time.perf_counter()
        sparse = []
        for d, dl in zip(corpus, lengths):
            score = 0
            for term in tokens(q['query']):
                freq = d[term]
                idf = math.log(1+(n-df[term]+0.5)/(df[term]+0.5))
                score += idf * freq * 2.5 / (freq + 1.5 * (0.25 + 0.75*dl/avgdl))
            sparse.append(score)
        rank_b = sorted(range(n), key=lambda j: (-sparse[j], docs[j]['id']))
        rankings = {'BM25': rank_b}
        if vectors:
            dense = [sum(a*b for a,b in zip(v, vectors[n+qi])) for v in vectors[:n]]
            rank_d = sorted(range(n), key=lambda j: (-dense[j], docs[j]['id']))
            rrf = {j: 1/(60+rank_b.index(j)+1)+1/(60+rank_d.index(j)+1) for j in range(n)}
            rankings.update(dense=rank_d, hybrid_rrf=sorted(range(n), key=lambda j: (-rrf[j], docs[j]['id'])))
        elapsed = 1000 * (time.perf_counter() - start)
        for name, ranking in rankings.items():
            ids = [docs[j]['id'] for j in ranking]
            eligible = bool(q['relevant']) and not q.get('expected_behavior')
            details.append({'query_id': q['id'], 'category': q['category'], 'method': name,
                            'ranking': ids[:5], 'eligible': eligible,
                            'metrics': metrics(ids, q['relevant']) if eligible else None,
                            'combined_ranking_cpu_ms': elapsed})
    summary = {}
    for name in sorted({x['method'] for x in details}):
        rows = [x['metrics'] for x in details if x['method'] == name and x['eligible']]
        summary[name] = {'n':len(rows), **{k:statistics.mean(x[k] for x in rows) for k in rows[0]}}
    result = {'scope':fixture['scope'],
              'fixture_sha256': hashlib.sha256((ROOT / 'tests/benchmark/retrieval_audit_fixture.json').read_bytes()).hexdigest(),
              'evaluator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'summary':summary, 'details':details,
              'limitations':['20 documents; synthetic developer-authored queries; no production challenge coverage',
              'No reranker or local sentence-transformer measured; no deployment agent tested',
              'Dense query embeddings batched offline; ranking CPU time excludes network/model time',
              'No confidence threshold calibrated; no claim of missing-data rejection performance']}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'retrieval_results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
