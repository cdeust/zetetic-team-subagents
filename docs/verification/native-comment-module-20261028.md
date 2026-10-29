# Native comment boundary extraction, 2026-10-28

The P1 editor-authentication implementation exceeded the consuming Cortex project's300-line module cap: runtime320 lines and reader335. Source: `scripts/craftsmanship_rules.py`, FILE_LINE_LIMIT300 and METHOD_LINE_LIMIT40, at the pinned Cortex source commit8e7375bf2edfb33fb9c45809b9af6b428f0f4235. No baseline waiver or rule change is used.

The cohesive GitHub comment query, response normalization and editor-authentication functions now live in `ci_codex_review_comments.py`. Runtime compatibility wrappers preserve `_comment_pages` and `summary_comments` with their existing request callbacks. The reader imports its existing private classification/authentication names. The comment module imports the same RuntimeEvidenceError class.

All six moved function definitions were compared with their P1 HEAD source segments and remained byte-identical: `_canonical`, `_bot_author`, `_authenticate_editor`, `_comment_row`, `_comment_pages` and `summary_comments`. The editor, immutable-ID, marker-removal, pagination and head-binding rules are unchanged.

Module sizes after extraction: runtime235 lines, reader287, comments166. The actual Cortex craftsmanship detectors scanned all three complete source files with their intended scripts paths and returned no file-size, method-size, import-layer or constant-provenance violations.

The review job explicitly preloads three trusted embedded payloads in order: runtime, comments, reader. Rendering delivers the additional module and records its SHA256. Script/payload equality checks cover all three. An isolated execution test loads the delivered files with an untrusted candidate path, verifies the shared error-class identity and exercises both positive review evidence and malformed-page rejection.

Existing Codebase regression entry point:26 tests pass after extraction. No model was called and no GitHub comment was modified.

Final SHA256:

- Runtime: `5aab93069cfc31d09648f27e504df763fad34632c708c682b720005ac0dcaf9e`.
- Reader: `854c0361003a185dceb457a1cdeeaeb4b6db2e7cba81ce255ebda58ea9d83d1d`.
- Comments: `a416d2dbda7d18f10f92809fd66c09bbc14e2deb2dc518579aa21ed584c14145`.
