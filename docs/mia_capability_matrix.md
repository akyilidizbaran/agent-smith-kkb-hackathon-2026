# MIA Capability Matrix (measured)

- base_url: `https://mia.csp.kloudeks.com/v1`
- chat: `kkbhackathon2026/Qwen3.8-27B`
- embedding: `kkbhackathon2026/Qwen3-Embedding-8B`
- ocr: `kkbhackathon2026/Unlimited-OCR`
- generated: 2026-09-10 21:11:24

| Capability | Result | Detail | Architecture impact |
|---|---|---|---|
| GET /models | OK | kkbhackathon2026/Qwen3.8-27B, kkbhackathon2026/Qwen3-Embedding-8B, kkbhackathon2026/Unlimited-OCR | Model adları doğrulandı |
| Basic chat | OK | 0.3s usage={'prompt_tokens': 68, 'completion_tokens': 36, 'total_tokens': 104, 'completion_tokens_details': {'reasoning_tokens': 30}} |  |
| Thinking default | OK | <think> in content=False; reasoning field=True | Varsayılan davranış kaydedildi |
| chat_template_kwargs.enable_thinking=false | OK | 0.1s thinking_off=True usage={'prompt_tokens': 28, 'completion_tokens': 4, 'total_tokens': 32, 'completion_tokens_details': {'reasoning_tokens': 0}} | Araç turları için kullanılabilir |
| reasoning_effort=none | OK | 0.2s thinking_off=True usage={'prompt_tokens': 28, 'completion_tokens': 4, 'total_tokens': 32, 'completion_tokens_details': {'reasoning_tokens': 0}} | Araç turları için kullanılabilir |
| reasoning_effort=low | OK | 0.3s thinking_off=False usage={'prompt_tokens': 56, 'completion_tokens': 37, 'total_tokens': 93, 'completion_tokens_details': {'reasoning_tokens': 31}} | Thinking kapanmadı |
| Second system message | REJECT | HTTP 400: {"error": {"message": "System message must be at the beginning.", "type": "invalid_request_error"}} | Workspace durumu ilk system mesajına gömülmeli |
| tools / tool_choice | OK | 0.4s tool_calls=[{"id": "chatcmpl-tool-b87068c55e76e5bd", "type": "function", "function": {"name": "get_series", "arguments": "{\"series_id\": \"evds:TP.KTF10\", \"start\": \"2 | Native tool calling kullanılabilir |
| Parallel tool_calls (E1) | OK | calls per turn over 3 runs=[3, 3, 3] | Paralel executor tur sayısını düşürür |
| Thinking+tools (thinking=false) | OK | 0.5s tool_calls=1 xml_in_content=0 reasoning=False |  |
| Thinking+tools (thinking=default) | OK | 1.1s tool_calls=1 xml_in_content=0 reasoning=True |  |
| Prefix caching (E3) | WEAK | first=0.90s median_rest=0.92s gain=-2% | Prefix caching kapalı görünüyor; prompt'u kısalt |
| System message adherence | WEAK | 7/10 | Prompt tasarımı |
| JSON reliability (prompt-only) | OK | raw 27/30, after extract 30/30, median 2.0s | Prompt-only JSON fallback kalitesi |
| response_format=json_object | OK | 2.9s keys=['intent', 'goal', 'steps', 'assumptions'] | Structured output kullanılabilir |
| response_format=json_schema | OK | 3.5s keys=['intent', 'goal', 'steps', 'assumptions'] | Structured output kullanılabilir |
| Long prompt (~30k tok) | OK | 4.7s usage={'prompt_tokens': 49871, 'completion_tokens': 9, 'total_tokens': 49880, 'completion_tokens_details': {'reasoning_tokens': 0}} found=True | Katalog özeti token eşiği (E8) buradan kalibre edilir |
| Latency short (n=5) | OK | p50=0.16s max=0.16s | Tur sabit maliyeti |
| Concurrency 5 parallel | OK | codes=[200, 200, 200, 200, 200] max=0.23s | 429 varsa semafor 2 |
| Determinism (T=0, seed=42, n=5) | OK | 1 distinct outputs | pass^k ölçümünde tolerans |
| Error format (bad model) | OK | HTTP 403: {"allowed_models":["kkbhackathon2026/Qwen3-Embedding-8B","kkbhackathon2026/Qwen3.8-27B","kkbhackathon2026/Unlimited-OCR"],"error":"Model not allowed for your li headers={} | Error taxonomy; rate-limit header var mı |
| Embeddings basic | OK | dim=4096 0.1s sim(faiz)=0.667 sim(KFE)=0.536 | Doğru seri daha yakın |
| Embeddings dimensions=1024 (MRL) | REJECT | HTTP 400 | 4096 sakla ya da client-side kes+normalize |
| Embeddings batch=64 | OK | HTTP 200 | Index build batch boyutu |
| Streaming (SSE) | OK | 6 chunks | Cevap turu UI'da akıtılabilir (algılanan hız) |
