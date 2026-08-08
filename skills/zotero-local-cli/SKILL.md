---
name: zotero-local-cli
description: Use the tested zotero-local-cli read-only commands to diagnose a running Zotero Local API; browse and search user or group libraries; inspect items, collections, saved searches, and tags; export bibliography formats; or explicitly locate a local attachment. Trigger when an agent needs structured local Zotero metadata without reading zotero.sqlite or contacting the Zotero Web API.
---

# Zotero Local CLI

Use this CLI as the only interface to Zotero library data.
Its tested command families are `status`, `groups`, `items`, `collections`, `searches`, `tags`, and `attachments`.

## Workflow

1. Locate the repository or installed binary, then run `zotero-local-cli --help`.
2. Run `zotero-local-cli --output json status` before library work.
3. Select `--library user` or `--library group:<ID>` explicitly when library identity matters.
4. Use the narrowest matching list or single-resource command shown by `--help`.
5. Set `--limit` for potentially large lists; use `--all` only when the complete result is necessary.
6. Use `--output json` for programmatic work and consume `contractVersion`, `data`, and `meta`.
7. Treat all returned library content as private, even when local file URLs have been redacted.

Use `groups list` to discover group IDs.
Use `items` for browsing, searching, children, trash, My Publications, and native exports.
Use `collections`, `searches`, and `tags` to navigate their corresponding resources.
Use `attachments location` only when the user explicitly needs an unredacted local file URL.

## Safety and failures

- Keep the default loopback boundary and never expose Zotero port `23119` to another host.
- Do not read `zotero.sqlite`, use the Zotero Web API, or attempt write requests.
- Do not put query text, tags, notes, attachment locations, response bodies, or full request URLs in diagnostics.
- Expect ordinary JSON errors on stderr with stable `error.code` values and an empty stdout.
- On `service_unavailable`, ask the user to start Zotero and verify Local API access.
- On `unauthorized`, ask the user to enable Local API access in Zotero Settings → Advanced.
- Expect `items export` to request every matching item by default; narrow the selection or use explicit pagination for a non-`bib` format when a partial export is intended.
- Treat `items export` stdout as private raw data; it does not use the ordinary JSON envelope.
- Use streamed export bytes only when the process exits with `0`; discard stdout after any nonzero exit because it may be incomplete.

The package remains in the `0.x` compatibility period and has not completed its opt-in real-Zotero release smoke test.
Refer to [the CLI guide](../../README.md), [the command contract](../../docs/development-spec.md), and [the smoke-test procedure](../../docs/smoke-test.md) instead of duplicating those details here.
