# Design and boundaries

## Native-agent isolation

Native mode uses the client's existing tools and authentication. The skill specifies minimal-context workers, text-only return, one-image ownership, bounded concurrency, explicit progress artifacts and verified handoff. It is not an executable scheduler bundled by this repository. Capability and permission checks remain the client's responsibility.

The parent must not fork its full history into the image worker. Workers directly inspect their assigned image instead of recursively invoking the router. A successful task needs saved, associated result files and any required fresh review evidence. Stopping a worker is not assumed to reclaim a lifetime thread slot.

Routing preference is recorded by the installer in local runtime.json. The public default is auto; explicit native-agent or api preferences are supported. A known setup failure is recorded for the current task/batch, not a permanent global blacklist. Neither route silently falls back to inserting images into the parent.

## Independent API requests

A local Python process calls the configured Responses endpoint with one focused task and one to three images. It omits conversation linkage, previous_response_id and tools. The agent receives bounded text; complete textual observations are saved in a chosen JSON file.

Images are still encoded and transmitted to the provider. This reduces image retention in the main conversation; it does not make vision local-only or independent of provider reliability. store=false is a request parameter, not an audit of server storage.

Cache fingerprints include paths, image hashes, prompt, endpoint, model, detail, effort, instructions and output budget. Only the chosen output file is reused for observe passes. A review pass must make a fresh request, normally writing a separate artifact. Each actual API request gets a local unique request_id and elapsed time; neither field proves answer quality. A cache does not evaluate answer correctness. Text can lose visual detail, so preserve original images and verify important observations.

The API call runs in a dedicated subprocess. The parent supplies the payload/key through stdin and accepts only a completed textual result. A communication thread owns the pipes while the parent supervises the deadline; this also covers Windows stdin writes that can block before communicate checks its timeout. On expiry or interruption, the parent stops and reaps its worker, joins the communication thread and closes the streams. The worker cannot save final artifacts itself. This bounds ordinary stalls, not OS scheduling or remote provider execution. Structured error types guide task-level strategy without automatic retries.

## Why not rewrite a live JSONL?

The client can retain history in memory and hold a writer lock. A disk mutation does not establish which history subsequent requests use. Recovery therefore requires a stopped target, rejects the current session and held locks, preserves record order/non-image data and saves full backups. Checksums guard replacement and restoration.

The schema and locks are internal conventions; compatibility with every client version is not guaranteed. Unknown shapes stop mutation. Cumulative disk bytes, reconstructed-history estimates, recorded token usage and wire request size are different measurements.

## v0.1.0 scope

- Local images through permitted native vision agents or API-key-authenticated Responses providers.
- No plugin patch, MCP server, daemon, runtime hook or automatic deletion.
- No silent provider/model fallback, retries or image-return fallback.
- No historical-incident numbers or claimed speed improvements without reproducible evidence.
- Mutation requires POSIX locks; unsupported systems receive a readable error.

## Suggested evaluation

Use synthetic images and a disposable project. Compare identical tasks under direct image input and the independent helper. Record client/model/provider versions, source bytes, completion time, answer quality, errors and embedded-image counts in the main history. Measure wire request size separately without logging credentials; log size is not a substitute.

Separate network failures from history effects. Publish failures as well as successful runs. Current validation and unfinished work are recorded in VALIDATION.md.
