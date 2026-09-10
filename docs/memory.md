# Memory with evidence provenance

| Type | Stored content | Lifetime / trust |
|---|---|---|
| Working | Plan, observations, failures | Current TaskRecord; bounded excerpts go to the provider |
| Episodic | Task, changed files, executable outcome | Persistent, exact repository + commit |
| Reusable lesson | An actually passing command | Persistent, trace sequence + exit code provenance |

Memory writes occur only after successful verification and only when memory is enabled. The system does not store a model's proposed explanation as a trusted lesson. A trusted entry without provenance is rejected by storage. Retrieval excludes untrusted and invalidated entries and requires exact repository path and commit equality.

The API supports GET /memory and POST /memory/{id}/invalidate. The UI shows provenance and lets the operator invalidate a stale lesson. Invalidation is durable; it does not delete historical evidence. Changing repository version naturally removes old lessons from the eligible scope.

Exact-commit scope is intentionally conservative: it reduces stale advice but misses useful cross-version knowledge. The current ranker uses lexical overlap, not embeddings. No autonomous cross-repository transfer or model-generated durable policy is implemented.

The five-profile fixture ablation warms memory with a separate verified task: full retrieves two memory chunks while memory-OFF configurations retrieve none. All repairs were already scripted, so this measures wiring rather than memory improving model intelligence.
