# Image Context Guard

![Image Context Guard cover](封面.jpg)

Analyze local images in isolated native agents or independent API requests, and keep the parent conversation focused on traceable text results.

[中文](README.md) · [Design](docs/DESIGN.md) · [Validation](docs/VALIDATION.md)

**Experimental, v0.1.0.** A community project, not an official OpenAI extension. It is a workflow, not a runtime interceptor, and does not guarantee recovery from network or context errors. All 56 offline tests passed. The refined native workflow also completed a synthetic one-image smoke test: two visual passes both read 4827, while embedded image entries in the parent log stayed at 0 → 0. This was same-worker review, not an independent reviewer or a performance benchmark. The API helper still lacks a successful real-provider test. See the [validation record](docs/VALIDATION.md).

## Two backends

| Backend | Behavior |
| --- | --- |
| native-agent | The skill guides an available, permitted client-native worker to read the image in its own context and return only text and file paths. |
| api | The Python helper sends a focused task and image to the configured Responses endpoint without parent history. |
| auto (default) | Prefer permitted native isolation when available; otherwise use a supported API route. |

The repository does not implement the client's agent launcher. The icg.py read CLI always uses the API backend. Selecting native-agent does not create agent capabilities or override delegation restrictions.

Native tasks normally own one image, with at most two concurrent workers. Save observations before reviewing; require fresh visual evidence for a requested second pass. Inspect stalled tasks before canceling; confirm the old owner stopped before one bounded replacement. Interrupting an agent does not necessarily release a thread slot. At a hard limit, preserve the checkpoint and report it. See the [native-agent protocol](skills/image-context-guard/references/native-agents.md).

Both routes preserve originals and traceable text artifacts. Do not repeat a known-broken API route for each image in a batch. Matching API observation results can be cached; explicit review passes cannot.

A separate recovery command audits and removes recognized image blocks from explicitly selected, stopped Codex histories, with backups and checksum-protected restoration. It cannot delete images from a running process or recall attachments already sent.

## API quick start

Requires Python 3.11+. From this repository on Linux/macOS:

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python icg.py read --image examples/demo.png --prompt-file examples/question.txt --out outputs/demo.json --dry-run
~~~

On Windows, create the environment with py -3.11 -m venv .venv and use .venv/Scripts/python.exe. History modifications require POSIX file locks; audit and vision reads do not. Windows and macOS have not been verified locally.

The helper reads CODEX_HOME/config.toml, falling back to ~/.codex/config.toml. It uses top-level model/provider settings, not temporary chat overrides. Active profiles are rejected. For separate configuration, copy examples/config.example.toml to a private directory as config.toml, fill in provider/model, and pass --codex-home.

Authentication uses the configured env_key first; otherwise CODEX_API_KEY, OPENAI_API_KEY or OPENAI_API_KEY in that directory's auth.json. Browser-login tokens and custom authentication headers/query parameters are unsupported. No key is included.

Remove --dry-run to make an actual, potentially billable API call. The synthetic image contains **4827**. This is an expected answer, not a recorded API success. Repeating an identical successful request with the same --out should return cached: true.

## Codex integration (both backends)

~~~bash
python install.py --dry-run
python install.py
~~~

Default destination: CODEX_HOME/skills/image-context-guard or ~/.codex/skills/image-context-guard. Use --skills-dir for other discovery locations, such as ~/.agents/skills. The installer records its Python executable; keep that environment available.

To merge a global instruction block after installation:

~~~bash
python install.py --with-global-rule --replace --backend auto
~~~

Existing installations require --replace and are backed up first. Other global instructions are preserved. AGENTS.override.md requires manual precedence review. Restart/reload Codex and invoke $image-context-guard once to confirm discovery. Automatic selection remains agent-driven.

For working native vision with a blocked direct API route, set --backend native-agent. The optional --max-native-agents defaults to 2; --no-progress-seconds defaults to 300 and triggers inspection, not automatic cancellation. Reinstallation preserves preferences that are not explicitly overridden.

## API errors, deadlines and review

--timeout bounds the request worker across upload and response handling. The parent stops/reaps that worker on expiry; no partial success is saved. Scheduling/cleanup overhead is possible, and server-side processing may continue. Credentials and images travel through a private pipe, not command-line arguments or temporary payload files.

Errors include error_type, phase, http_status, elapsed_seconds, retryable and next_action. Permission, proxy, authentication, rate-limit, service and timeout failures are distinguished. retryable is diagnostic; the helper does not automatically retry.

Use --review-pass review with a separate --out for a fresh visual request. Review results record a unique local request_id and elapsed time. They never reuse a cache; a new call is not a guarantee of independent or correct judgment.

## History tools

~~~bash
python icg.py history audit --session UUID
python icg.py history prune --session UUID --checkpoint /path/handoff.md
python icg.py history prune --session UUID --checkpoint /path/handoff.md --apply
python icg.py history restore --manifest /returned/manifest.json --apply
~~~

Replace UUID and paths. Omit --apply to preview. Close the target and stop its writer before mutation; never operate on the current conversation. Read the [recovery guide](skills/image-context-guard/references/recovery.md). Place --codex-home before the history subcommand when overriding the home.

## Development

~~~bash
python -m unittest discover -s tests -v
python tools/check_release.py
~~~

Tests use synthetic data and mocked responses; they do not read actual credentials or call providers. The release check is a limited guard against accidental private files, not a complete secret scanner. See [CONTRIBUTING.md](CONTRIBUTING.md). Licensed under [MIT](LICENSE).
