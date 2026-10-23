# Validation status

Version: v0.1.0 (experimental)

Recorded: 2026-10-23

## Completed locally

- Environment: Linux, Python 3.11.13.
- Command: python -m unittest discover -s tests -v
- Result after the CI path correction: **61 tests passed**, no skipped tests on this local POSIX run. The initial release had 56 tests.
- The packaged skill passed the local Codex skill-creator frontmatter/structure validator.
- Tests used temporary directories, synthetic images and histories, fake credentials, and mocked HTTP responses. They did not use real session files or call a provider.

Covered behavior:

- Independent payload: one focused user input, no conversation link or tools, store=false.
- Text result/provenance persistence, bounded console output, cache reuse and explicit refresh.
- Credential and image-data redaction in request errors; incomplete streams rejected.
- UTF-8 prompts and results; source-byte limits; unsupported settings rejected.
- History audit versus post-compaction estimate, preview without writes, active/locked history refusal.
- Preservation of text, record order and tool-call IDs; full backup and exact restoration.
- Refusal to restore over newer messages, unknown image metadata, or truncated JSONL.
- Index-schema fallback, unsupported-platform handling, installation backups and preservation of existing global rules.
- CLI help, deterministic synthetic fixture, and basic release-file checks.
- Real child-process deadline tests for a blocked upload and stalled output, with process reaping and pipe cleanup.
- Complete worker/JSON-pipe execution against a temporary local HTTP-library shim; no network requests.
- Structured permission/proxy/authentication/rate-limit/service/timeout errors and credential redaction.
- Fresh review requests with separate IDs/artifacts; cache never substitutes for a second visual request.
- Backend preferences, scheduling limits and preservation of settings on reinstall.
- Canonical home paths, directory aliases, restoration through an aliased home, external-manifest rejection and canonical custom-install destinations.

## First GitHub Actions run and path correction

The [first published matrix run](https://github.com/jiangweny/image-context-guard/actions/runs/39939151768) tested Python 3.11, 3.12 and 3.13 on Ubuntu, macOS and Windows. All three Ubuntu jobs passed; all six macOS/Windows jobs failed. Public failure annotations include the history tool rejecting a valid session as outside the configured home.

The containment checks resolved target paths but compared them against an unresolved home. Different path spellings for the same directory could therefore fail the check. The installer already returns a canonical destination, while one test expected an unresolved path.

The history selection and restore helpers now canonicalize the home before comparing paths. The installer assertion uses a resolved expected path. Five regression tests cover equivalent home paths, directory symlinks where supported, restore behavior and installation destinations; outside-directory rejection remains enforced. The original platform matrix and POSIX lock requirements are unchanged.

Before the correction, the new equivalent-home tests reproduced the session and manifest rejection errors locally. Afterward, all 61 tests passed on Linux, including a run with ResourceWarning treated as an error. A new macOS/Windows CI run is still required to establish the outcome on those runners.

## Observed native-agent workflow

One private task execution record, reviewed during development on 2026-10-23, reports eight remaining images completed through user-authorized isolated native agents and zero images added to the parent during that resumption. The same record reports failed direct API attempts, a thread limit and a stalled review that required a replacement worker.

This supports the usefulness of isolation in that environment. It is not a controlled benchmark or an independent audit of annotation correctness, and it predates the refined scheduling rules. The raw private images/session records are not distributed. The new native-agent workflow has not yet had a separate end-to-end production run.

## Synthetic native-agent smoke test

The refined workflow completed a live client-native smoke test on 2026-10-23 using only the repository's synthetic [demo image](../examples/demo.png). A fresh worker received the image path and task, without the parent conversation or expected answer. It saved a first observation, reopened the original for a second visual pass, and returned text and artifact paths to the parent.

- First observation and review both read **4827**, matching the known synthetic fixture.
- The worker recorded **two view_image operations**, with no cached review, no replacement and a completed task artifact.
- The first result was saved before the review. This was **same-worker review**, not an independent second reviewer.
- Separate read-only audits of the parent session recorded embedded image entries **0 before → 0 after**. Estimated post-compaction image entries also stayed at zero. No history was modified.
- The parent verified that the result files existed, parsed and referred to the intended image. View-call evidence comes from the worker's artifacts; it was not independently reconstructed from the worker's raw session log.

The [sanitized result](native-smoke-result.json) includes the fixture hash, observations, timestamps, parent image counts and these evidence limits. It excludes private paths, session identifiers, raw histories and credentials.

This verifies a small native workflow in one environment. It does not measure request-body size, in-memory context, latency improvements, crash rates, sustained batch behavior or direct API compatibility. The parent log counts are not a measurement of provider requests.

## Not yet established

- **Real-provider end-to-end vision success.** An earlier development request was blocked by the environment's proxy connection. This is not evidence that the provider accepted or rejected the image.
- Successful Windows or macOS results after the path correction. The initial jobs failed; a rerun of the corrected code is pending. POSIX history mutation tests intentionally skip on systems without fcntl; the directory-symlink regression skips only where symlink creation is unavailable.
- Compatibility with every Codex version, proxy, API model or authentication method.
- Measured improvements in request bytes, latency or failure rate in controlled comparisons.
- Automatic skill selection in every client session. The workflow is agent-guided, not a runtime interceptor.

## Reproduce locally

~~~bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python tools/check_release.py
~~~

The release checker verifies required files, relative documentation links and a limited set of accidental private artifacts. It is not a complete secret scanner or a proof of compatibility.

For a live API smoke test, configure a vision-capable Responses model and use the README command on examples/demo.png. Expected content: 4827. Record the model/provider, result, usage and cache behavior before updating this document. Keep private configuration, request bodies and raw output artifacts out of the repository.

For a native smoke test, follow the [worker protocol](../skills/image-context-guard/references/native-agents.md) with the synthetic image and a fresh worker. Ask for a first observation and a fresh review, and audit the parent history before and after. Do not give the worker the expected answer, the image generator, or this validation record. Check saved artifacts and retain the distinction between same-worker review and an independent reviewer. Any public result must be a manually reviewed, sanitized summary.
