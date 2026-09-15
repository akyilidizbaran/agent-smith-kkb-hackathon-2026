import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ResearchAuditTests(unittest.TestCase):
    def test_schema_rejects_shapes_previous_probe_accepted(self):
        m = module('mia_evidence_audit')
        good = {'action':'inspect_schema', 'dataset_id':'fixture_v1', 'limit':2}
        self.assertTrue(m.schema_ok(json.dumps(good)))
        for change in [{'limit':'2'}, {'limit':999}, {'limit':True},
                       {'action':'drop_table'}, {'extra':True}, {'dataset_id':'unknown'}]:
            self.assertFalse(m.schema_ok(json.dumps({**good, **change})), change)
        self.assertFalse(m.schema_ok('{"action":"inspect_schema","action":"drop_table"}'))
        self.assertFalse(m.schema_ok('```json\n' + json.dumps(good) + '\n```'))

    def test_multirelevant_recall_is_not_hit_rate(self):
        m = module('retrieval_evidence_audit')
        result = m.metrics(['a','x','b','y','z'], ['a','b'])
        self.assertEqual(result['recall@1'], 0.5)
        self.assertEqual(result['precision@1'], 1)
        self.assertEqual(result['recall@3'], 1)
        self.assertAlmostEqual(result['precision@3'], 2/3)
        self.assertEqual(result['mrr'], 1)
        self.assertAlmostEqual(result['ndcg@5'], 1.5/(1+1/__import__('math').log2(3)))

    def test_no_match_metrics(self):
        m = module('retrieval_evidence_audit')
        self.assertTrue(all(v == 0 for v in m.metrics(['x','y','z'], ['a']).values()))

    def test_fixture_labels_and_coverage(self):
        f = json.loads((ROOT/'tests/benchmark/retrieval_audit_fixture.json').read_text(encoding='utf-8'))
        ids = {x['id'] for x in f['documents']}
        self.assertEqual(len(ids), len(f['documents']))
        self.assertEqual(len({q['id'] for q in f['queries']}), 36)
        for q in f['queries']:
            self.assertTrue(set(q['relevant']) <= ids)
        self.assertEqual(sum(bool(q['relevant']) and not q.get('expected_behavior') for q in f['queries']), 32)


if __name__ == '__main__':
    unittest.main()
