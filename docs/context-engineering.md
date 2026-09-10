# Context engineering

`RepositoryContext` retrieves a bounded tree and text chunks from readable source/docs. Structured ranking combines lexical term frequency normalized for chunk length, path matches and a documentation prior. Symbol-bearing chunks are labelled separately. This is a BM25-like lexical heuristic, not embeddings or semantic understanding.

Naive retrieval preserves tree/file order. Structured retrieval sorts by relevance, with failure output, prior observations, current diff and verified memory given explicit priority. Chunk headers record source, path, start line and estimated tokens. The inspector exposes selected chunks and discarded candidates with budget reasons.

The token estimate is conservative UTF-8 bytes / 3 plus metadata, not a model tokenizer. Provider usage is the authoritative returned count. Full prompt budget checks include the system message and recent working memory; selected-context tokens are not total request tokens. Large or binary files, hidden dependency directories, symlinks and secret files are excluded.

Repository content can contain prompt injection. The provider instruction treats it as untrusted data, but this is not a security proof. Actual permissions are enforced by the router regardless of retrieved instructions. Redaction happens on text leaves so credentials do not corrupt JSON envelopes. These controls are tested; host-mode repository code remains trusted.

No retrieval improvement percentage is reported. The deterministic ablation only proves that structured context is attached and scoped memory is retrieved. Real model experiments and larger retrieval relevance labels are still needed to measure task-solving impact.
