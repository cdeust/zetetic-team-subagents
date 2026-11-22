# PR #174 review evidence

The eight review rounds retain their captured text at the original paths. Each round directory contains the measurements and notes recorded for that round. [Round 2](round2/) · [Round 3](round3/) · [Round 4](round4/) · [Round 5](round5/) · [Round 6](round6/) · [Round 7](round7/) · [Round 8](round8/) · [Round 9](round9/)

The original review committed the specimens, measurement programs and reports together. The inventory records every path in that immutable Git tree, including every name for files with identical bytes. The historical programs are available in that commit. The maintained gate and its regression tests live in the current project. [PR #174](https://github.com/cdeust/zetetic-team-subagents/pull/174) · [Original review directory](https://github.com/cdeust/zetetic-team-subagents/tree/986aa55c27ffcba3cfa42d2b4a1728bb5ae0bebc/tasks/evidence/pr-174-review) · [Gate tests](../../../tests/test_gate_targets.py)

## Provenance

Each entry in [provenance.json](provenance.json) gives the path relative to the original directory, Git mode, blob object ID, byte length and SHA-256 of the exact recorded bytes. The top-level fields identify the source commit, directory and Git tree. To locate an entry, open its relative path in the original directory linked above.

The [provenance tests](../../../tests/test_pr174_evidence.py) reconstruct the original Git tree from paths, modes and blob IDs. They check byte lengths and SHA-256 values against a fingerprint measured from the original blobs, and hash each retained report directly. These checks also run in a shallow checkout. To run them from the repository root, use `python3 -m unittest discover -s tests -p test_pr174_evidence.py`.
