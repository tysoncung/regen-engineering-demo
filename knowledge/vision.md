# Vision

A deliberately small commerce system, existing to prove one claim:

> The same knowledge regenerates into different stacks, and one contract suite
> verifies all of them.

There are two implementations here, TypeScript and Python. Neither was written
from the other. Both were generated from the knowledge in this repository, and
both are verified by the same contracts, executed by the same runner.

If you want to check the claim rather than take it on faith, delete either
implementation directory and regenerate it. That is the Regeneration Test, and
this repository exists to be a place where you can run it in five minutes.

## Deliberate constraints

- No frameworks and no dependencies in either implementation, so the demo runs
  anywhere Node and Python are installed.
- Storage is in memory. Persistence would add plumbing without adding anything
  to the argument.
- The domain is boring on purpose. The interesting part is the structure.
