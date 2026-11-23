---
name: add-provider
description: Add a new swappable implementation to VendorGuard - an LLM, embedder, decider, memory store or cache backend - without touching the pipeline. Use whenever a new provider or service integration is needed.
---

# Add a provider

Every provider is: **one file + one registry entry + one config block + tests**. The pipeline never changes.

1. **Pick the interface** in `src/vendorguard/interfaces/` (`LLMClient`, `Embedder`, `Decider`,
   `MemoryStore` / `MemoryAssistant`, `CacheBackend`). Do not change the interface unless an ADR says so.
2. **Create the file** `src/vendorguard/providers/<kind>/<name>.py` (≤ 150 lines). Split HTTP details into a
   separate `<name>_client.py` if the file grows. The constructor takes only its settings section (plus
   other providers if needed); no `get_settings()` calls inside.
3. **Configuration:** add a block under the right section in `config/settings.yaml` with comments
   (base_url, model, timeouts, limits). Add matching typed fields in `src/vendorguard/config.py`. Any key
   goes in as an empty `api_key: ""` in YAML, a `SecretStr` field, and a `VG_..._API_KEY=` line in
   `.env.example`.
4. **Register** it in the matching registry in `src/vendorguard/factory.py`. Paid providers must be wrapped
   in the cache and, for deciders, in `fallback.py`.
5. **Cost:** add a price entry in `cost.prices_per_million_tokens` (0 for free/local).
6. **Tests:** offline unit tests with `respx` or fakes (use the `test-writer` sub-agent); a live test behind
   a marker (`ollama`, `letta`, `jev`) if it calls a real service.
7. **Docs:** a line in the README "Swappable providers" table and an ADR in `docs/DECISIONS.md`.
8. Run `make check`, then `/checkpoint`.
