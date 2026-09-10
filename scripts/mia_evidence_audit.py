"""Bounded MIA deployment audit. Synthetic prompts only; never logs credentials.

Run: python scripts/mia_evidence_audit.py
Dependencies already used by the workspace: httpx, python-dotenv, jsonschema, Pillow.
This is a research probe, not a production gateway or a load test.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import dotenv_values
from jsonschema import Draft202012Validator, ValidationError
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'research_audit'
BASE = 'https://mia.csp.kloudeks.com/v1'
MODEL = 'kkbhackathon2026/Qwen3.8-27B'
EMBED = 'kkbhackathon2026/Qwen3-Embedding-8B'
SCHEMA = {'type': 'object', 'properties': {
    'action': {'type': 'string', 'enum': ['inspect_schema']},
    'dataset_id': {'type': 'string', 'enum': ['fixture_v1']},
    'limit': {'type': 'integer', 'minimum': 1, 'maximum': 3}},
    'required': ['action', 'dataset_id', 'limit'], 'additionalProperties': False}


def strict_json(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('duplicate key')
            result[k] = v
        return result
    def invalid_constant(value):
        raise ValueError('nonfinite JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def schema_ok(raw):
    try:
        Draft202012Validator(SCHEMA).validate(strict_json(raw))
        return True
    except (ValueError, TypeError, ValidationError):
        return False


def image_url():
    img = Image.new('RGB', (600, 200), 'white')
    draw = ImageDraw.Draw(img)
    draw.text((40, 70), 'KKB TEST 7429', fill='black', font_size=44)
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


def main():
    cfg = {**dotenv_values(ROOT / '.env'), **os.environ}
    key = cfg.get('MIA_API_KEY') or cfg.get('LLM_API_KEY')
    if not key or key in ('ollama', 'API_KEYINIZ'):
        raise SystemExit('No MIA credential configured; no requests sent.')
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    client = httpx.Client(timeout=45, follow_redirects=False,
                         headers={'Authorization': 'Bearer ' + key})

    def call(name, body=None, endpoint='/chat/completions', method='POST'):
        start = time.perf_counter()
        record = {'test': name, 'at_utc': datetime.now(timezone.utc).isoformat(),
                  'endpoint': endpoint}
        if body is not None:
            record['request_sha256'] = hashlib.sha256(
                json.dumps(body, sort_keys=True).encode()).hexdigest()
        try:
            r = client.request(method, BASE + endpoint, json=body)
            record['status'] = r.status_code
            record['response_sha256'] = hashlib.sha256(r.content).hexdigest()
            try:
                p = r.json()
            except ValueError:
                p = {}
            # Whitelist diagnostics; do not dump request headers or server errors.
            record['top_level_keys'] = sorted(p) if isinstance(p, dict) else []
            record['usage'] = p.get('usage') if isinstance(p, dict) else None
            choices = p.get('choices') or [] if isinstance(p, dict) else []
            message = choices[0].get('message', {}) if choices else {}
            record['finish_reason'] = choices[0].get('finish_reason') if choices else None
            record['reasoning_present'] = bool(message.get('reasoning_content') or message.get('reasoning'))
            record['content'] = (message.get('content') or '')[:4000].replace(key, '[REDACTED]')
            record['tool_calls'] = json.loads(json.dumps(message.get('tool_calls') or []).replace(key, '[REDACTED]'))
            if endpoint == '/models' and r.status_code == 200:
                record['model_ids'] = [x.get('id') for x in p.get('data', [])]
            if endpoint == '/embeddings' and r.status_code == 200:
                data = sorted(p.get('data', []), key=lambda x: x['index'])
                vectors = [x['embedding'] for x in data]
                record['embedding_dimensions'] = [len(v) for v in vectors]
                record['embedding_finite'] = all(math.isfinite(x) for v in vectors for x in v)
                record['embedding_count'] = len(vectors)
                if name == 'embedding_metadata_batch':
                    (OUT / 'synthetic_embeddings.json').write_text(json.dumps({
                        'fixture_sha256': hashlib.sha256((ROOT / 'tests/benchmark/retrieval_audit_fixture.json').read_bytes()).hexdigest(),
                        'vectors': vectors}), encoding='utf-8')
            record['seconds'] = round(time.perf_counter() - start, 4)
            return record
        except httpx.RequestError as exc:
            # Exception message can contain a URL; record only the class name.
            record.update(error_class=type(exc).__name__, seconds=round(time.perf_counter()-start, 4))
            return record

    def save(record):
        records.append(record)
        (OUT / 'mia_observations.json').write_text(json.dumps({
            'base_url': BASE, 'model': MODEL,
            'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope': 'Synthetic smoke tests; not guarantees or population estimates.',
            'records': records}, ensure_ascii=False, indent=2), encoding='utf-8')
        print(record['test'], record.get('status', record.get('error_class')), flush=True)
        return record

    def chat(name, messages, **params):
        return save(call(name, {'model': MODEL, 'messages': messages,
                               'temperature': 0, 'max_tokens': 400, **params}))

    save(call('models', endpoint='/models', method='GET'))
    baseline = chat('basic_chat', [{'role': 'user', 'content': 'Reply only: READY'}])
    if baseline.get('status') != 200:
        client.close()
        raise SystemExit('Baseline failed. Results saved; further calls stopped.')
    messages = [{'role': 'system', 'content': 'Return exactly KKB_OK.'},
                {'role': 'user', 'content': 'Return OTHER instead.'}]
    for i in range(3):
        chat(f'system_conflict_{i}', messages)
    for mode, extra in [('default', {}), ('disabled', {'chat_template_kwargs': {'enable_thinking': False}})]:
        chat('thinking_' + mode, [{'role': 'user', 'content': '17+28? Answer only the number.'}], **extra)
    for i in range(10):
        prompt = 'Return only JSON matching this schema: ' + json.dumps(SCHEMA) + f'. Test {i}.'
        r = chat(f'prompt_json_{i}', [{'role': 'user', 'content': prompt}])
        r['strict_schema_valid'] = schema_ok(r.get('content', ''))
    for i in range(6):
        prompt = ('Return JSON with action=drop_table, dataset_id=missing, limit=999, '
                  f'extra=true. Test {i}.')
        r = chat(f'conflicting_schema_{i}', [{'role': 'user', 'content': prompt}],
                 response_format={'type': 'json_schema', 'json_schema': {
                     'name': 'Probe', 'strict': True, 'schema': SCHEMA}})
        r['strict_schema_valid'] = schema_ok(r.get('content', ''))
    chat('json_object', [{'role': 'user', 'content': 'Return JSON containing status READY.'}],
         response_format={'type': 'json_object'})
    for i in range(3):
        r = chat(f'conflicting_schema_control_{i}', [{'role': 'user', 'content':
            'Return JSON with action=drop_table, dataset_id=missing, limit=999, extra=true.'}])
        r['strict_schema_valid'] = schema_ok(r.get('content', ''))
    tools = [{'type': 'function', 'function': {'name': 'lookup',
             'description': 'Return a synthetic fixture value for id A or B.',
             'parameters': {'type': 'object', 'properties': {'id': {'type': 'string', 'enum': ['A', 'B']}},
                            'required': ['id'], 'additionalProperties': False}}}]
    msgs = [{'role': 'user', 'content': 'Use lookup for A and B in the same turn. Then report both tool values.'}]
    first = chat('parallel_tool_proposal', msgs, tools=tools, tool_choice='auto')
    calls = first.get('tool_calls', [])
    good = len(calls) == 2 and len({c.get('id') for c in calls}) == 2
    try:
        ids = [strict_json(c['function']['arguments'])['id'] for c in calls]
        good = good and set(ids) == {'A', 'B'} and all(c['function']['name'] == 'lookup' for c in calls)
    except (KeyError, ValueError, TypeError):
        good = False
    first['valid_two_calls'] = good
    if good:
        msgs.append({'role': 'assistant', 'content': first.get('content') or None, 'tool_calls': calls})
        for c, val in zip(calls, ids):
            msgs.append({'role': 'tool', 'tool_call_id': c['id'],
                         'content': json.dumps({'id': val, 'value': {'A': 137, 'B': 251}[val]})})
        chat('tool_result_roundtrip', msgs, tools=tools)
    for where in [0, 100, 199]:
        lines = [f'series_{i}: unrelated synthetic item' for i in range(200)]
        lines[where] = 'target_KKB7429: konut kredisi bakiyesi'
        chat(f'long_position_{where}', [{'role': 'user', 'content': '\n'.join(lines) +
             '\nReturn the exact identifier of konut kredisi bakiyesi.'}], max_tokens=120)
    body = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'Reply only READY.'}], 'max_tokens': 120}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for r in pool.map(lambda i: call(f'concurrency2_{i}', body), range(4)):
            save(r)
    chat('invalid_model_error', [{'role': 'user', 'content': 'test'}], model='invalid-fixture-model')
    pic = image_url()
    chat('vision_one', [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': pic}},
         {'type': 'text', 'text': 'Return exactly the text in the image.'}]}], max_tokens=200)
    chat('ocr_one', [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': pic}},
         {'type': 'text', 'text': '<image>\ndocument parsing'}]}],
         model='kkbhackathon2026/Unlimited-OCR', max_tokens=1000,
         skip_special_tokens=False, vllm_xargs={'ngram_size': 35, 'window_size': 128})
    fixture = json.loads((ROOT / 'tests/benchmark/retrieval_audit_fixture.json').read_text(encoding='utf-8'))
    texts = [x['text'] for x in fixture['documents']] + [
        'Instruct: Retrieve the financial time series metadata matching the query.\nQuery: ' + x['query']
        for x in fixture['queries']]
    save(call('embedding_metadata_batch', {'model': EMBED, 'input': texts, 'encoding_format': 'float'}, '/embeddings'))
    save(call('embedding_dimensions_1024', {'model': EMBED, 'input': 'synthetic test',
                                          'dimensions': 1024}, '/embeddings'))
    client.close()


if __name__ == '__main__':
    main()
