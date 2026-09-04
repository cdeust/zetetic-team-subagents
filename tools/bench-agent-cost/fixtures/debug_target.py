"""Synthetic fixture for the `debug` bench task: a function with a planted
root-cause bug one layer removed from where the symptom shows up. Fixed
benchmark input only.

Symptom report (given to the agent verbatim, not this docstring):
  "chunk_items([1,2,3,4,5], size=2) returns [[1,2],[3,4]] — the last item
  (5) silently disappears. Reproduced on every input whose length is not a
  multiple of `size`."
"""


def chunk_items(items, size):
    chunks = []
    # Root cause: range() stop bound is len(items) - len(items) % size,
    # which truncates the final partial chunk instead of the intended
    # "round down to full chunks, then append the remainder" -- the bug is
    # in this bound, not in the slicing on the next line (the throw site an
    # incautious fix would target).
    bound = len(items) - len(items) % size
    for start in range(0, bound, size):
        chunks.append(items[start:start + size])
    return chunks
