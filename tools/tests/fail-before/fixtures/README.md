# Node empty-file specimen

Captured on macOS arm64, 2026-09-17, with Node 20.20.2 installed in an isolated npm cache. The file contained only `// no tests`. From `/private/tmp/pr140-node20`, the command was:

```sh
node --test --test-reporter=tap tests/empty.test.js
```

The TAP output reports one passing file wrapper with an absolute path. Node 24.7.0 uses the relative path for the same fixture. The shell suite substitutes its own temporary directory into this captured specimen before checking the parser. The real-runner suite checks the same behavior with the installed runtime.
