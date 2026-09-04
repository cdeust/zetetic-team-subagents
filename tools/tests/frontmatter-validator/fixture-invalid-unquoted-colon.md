---
name: fixture-invalid-unquoted-colon
description: "Reproduces the exact HC-ZETETIC-003 defect: an unquoted plain scalar containing a colon-space, which YAML 1.1/1.2 parses as a nested mapping key and rejects."
category: fixture
output: Report: this colon-space sequence is what breaks strict YAML parsing
---

Body content, not parsed.
