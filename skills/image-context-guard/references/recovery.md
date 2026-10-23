# History recovery and limitations

## Stop the target before editing

Codex may hold both in-memory history and a disk writer lock. Editing disk does not establish what the next live request contains. This tool does not implement hot deletion, a background watcher or an automatic post-image cleanup hook.

1. Save a meaningful text checkpoint: observations, original image paths, coordinate conventions, uncertainties and remaining tasks. Do not mark unseen images as analyzed.
2. Use another conversation or terminal. Close the target and confirm its owning process has stopped writing. A reload can reopen a writer; a held lock still means stop.
3. Resolve this skill's Python interpreter and scripts directory. Preview:

~~~text
<python> <skill-dir>/scripts/prune_history.py prune --session UUID --checkpoint /absolute/path/handoff.md
~~~

4. Add --apply only for the user-authorized target. The script saves the original JSONL and a checksum manifest under CODEX_HOME/image-context-backups/. Use the returned manifest path for restoration.
5. Reopen the target to load the cleaned history. Old image payloads become short text placeholders; prior text and tool-call IDs are preserved. Original image files are not deleted.

## Restore

~~~text
<python> <skill-dir>/scripts/prune_history.py restore --manifest /path/to/manifest.json
<python> <skill-dir>/scripts/prune_history.py restore --manifest /path/to/manifest.json --apply
~~~

Restoration validates the backup, session identity and current checksum under the writer lock. It refuses to overwrite newer messages. Backups contain the original private conversation and images; they are not automatically deleted or suitable for publication.

## Compatibility

- Mutation requires POSIX fcntl locks; unsupported systems can audit but cannot prune or restore.
- The known schema uses session_meta, response_item, compacted and input_image blocks with data-image URLs. Unknown metadata or shapes are rejected.
- Index lookup uses state_5.sqlite when available, then exact UUID filenames. A full session path avoids index assumptions.
- Writer locks use thread-writer-locks/<UUID>.lock. This is an internal convention, not a stable public contract. A successful lock does not prove every older or future client uses it: stopping the target remains required.
- Incomplete JSONL, unknown image records, a changed file or a held lock produces an error. There is no force option.
- The helper loads the selected file in memory; large logs can require substantially more RAM than their disk size.

## Scope

Images still go to the configured provider. store=false requests disabled response storage; this does not independently guarantee third-party logging or retention. Text results contain prompts, paths and observations and can themselves be sensitive.

Skills guide behavior; they do not enforce it. Pictures already pasted into a conversation cannot be recalled. Network and context problems may have causes unrelated to images. Disk log size is not request size, and a cache miss does not necessarily replay every log record.
