# Friction log: running the change loop on BR-011

**Task T018.** One sentence of product change, "a customer may have at most 20
addresses, and a 21st is rejected with 409 and a generic message", taken through
`/knowledge-delta`, `/impact`, `/regenerate`, `/verify`, `/drift-check` exactly
as the published skill files describe them, in this repository, on
`feature/address-limit`.

Outcome: both stacks green, 24/24 scenarios across 5 contracts, validator clean,
drift clean. That result is the least interesting part of this document.

Everything below was hit while following the skills literally rather than doing
what I would have done anyway. Commands and output are quoted verbatim.

---

## 1. Every command in every skill is a command that does not exist

All five skill files instruct you to run the tooling through `npx`:

```
npx regen-validate .
npx regen-impact BR-002
npx regen-debt .
```

None of those resolve. Neither the bin names nor the package name are on the
public registry:

```
$ npx --no-install regen-validate .
npm error 404 Not Found - GET https://registry.npmjs.org/regen-validate

$ npm view regen-engineering-schema version
npm error 404 Not Found - GET https://registry.npmjs.org/regen-engineering-schema
```

This repository's own CI already knows, and says so in a comment:

```yaml
# The schema tooling is not on npm yet, so use the repo directly rather
# than an npx invocation that would only pretend to work.
```

So the published skills document a workflow that the project's own pipeline
abandoned, and no skill offers a fallback. Following them literally, the first
command of the first step fails, and there is no instruction for what to do
next. I had to find the tools by path and read all five of them to learn the
correct invocation and the tree argument, which is why this exercise spent about
15 minutes before writing a single word of knowledge.

There is a sharper edge on this. `npx regen-validate .` does not merely fail
today. It resolves a name on a public registry that nobody here owns. The first
person to publish a package called `regen-validate` gets arbitrary code
execution on the machine of every reader who follows the instructions. A
methodology whose whole pitch is "the knowledge is the source of truth" should
not ship a supply chain hazard in its five most-read files.

**Fix:** replace every `npx regen-*` line with a resolution block that prefers a
local install, falls back to the repo, and says what to do if neither is
present. The CI already contains a working version of that block.

## 2. `regen-impact --changed` is broken exactly as the skill documents it

The `impact` skill says:

```bash
npx regen-impact --changed $(git diff --name-only main...HEAD)
```

`--changed` is greedy and consumes every remaining argument, `impact.mjs` has no
`--tree` flag (`drift.mjs` does), so the tree silently falls back to the default
`example` and the tool dies with a raw stack trace:

```
$ node .../impact.mjs --changed customer/knowledge/rules/BR-011.md . 
node:fs:1597
Error: ENOENT: no such file or directory, scandir
  '/Users/.../regen-engineering-demo/example'
    at readdirSync (node:fs:1597:26)
    at walk (.../tools/lib/load.mjs:15:23)
```

The working invocation is `REGEN_TREE=. node impact.mjs --changed <files>`, and
the environment variable appears in no skill. Cost: about 5 minutes and a
detour into the loader source.

**Fix:** add `--tree` to `impact.mjs` for parity with `drift.mjs`, catch ENOENT
on the tree root and print "no knowledge tree at X, pass --tree", and correct the
example in the skill.

## 3. The two impact modes disagree and the skill has no rule for that

```
$ impact.mjs BR-011 .
Modules to regenerate (1): customer
Contracts that must pass (4): CT-001, CT-002, CT-003, CT-004
Untouched: orders

$ REGEN_TREE=. impact.mjs --changed <the actual diff>
Modules to regenerate (2): customer, orders
Contracts that must pass (5): CT-001, CT-002, CT-003, CT-004, CT-010
```

Both are correct by their own definitions. The second pulls in `orders` because
I edited one sentence of BR-002, whose `affects` includes `orders`, and that
sentence was a cross-reference: "up to the limit set by BR-011". A purely
editorial edit to a widely-linked item inflated the blast radius by a module.

On a tree with fifty rules this is precisely how the scope becomes "everything",
which the impact skill itself calls out as equivalent to having no impact
analysis. The skill tells you to sanity-check the computed scope against the
prose but gives no guidance on which of its own two modes to believe.

**Fix:** state in the skill that the ID mode is authoritative for a new item and
the `--changed` mode is a review aid, or teach the tool the difference between a
frontmatter/body change and a whitespace/cross-reference change.

## 4. The drift check cannot see this repository's implementations at all

This is the finding I would fix first.

The `drift-check` skill's mechanical rule is "if a change touches a module's
generated paths and contains no corresponding change to that module's
knowledge". `drift.mjs` implements that by taking the first path segment of a
changed file and asking whether it names a module. In this repository the
implementations live in `impl/typescript/` and `impl/python/`, so the first
segment is `impl`, which is not a module. Result:

```
$ drift.mjs --tree . --changed impl/typescript/server.mjs impl/python/server.py contracts/run.mjs
Drift check  /Users/.../regen-engineering-demo
3 changed file(s), 0 module(s) touched

No code-ahead drift. Every module with implementation changes also changed its knowledge.
```

I can rewrite both servers, change every status code in the system, and touch no
knowledge, and the drift check reports clean and exits 0. Step 5 of this
exercise asked for "drift clean because knowledge moved with code". Drift was
clean, but it would have been clean regardless, so it is not evidence of
anything here.

The root cause is that nothing anywhere maps a module to the files that
implement it. `knowledge.lock` records which knowledge produced an
implementation but not which files that implementation is. The tool then guesses
from directory layout and fails silently when the guess does not fit.

**Fix, two parts:**
1. Add `generated_paths:` to the lock schema (`[impl/typescript/server.mjs]`)
   and have `drift.mjs` attribute changed files through it before falling back
   to directory layout.
2. Make an unattributable non-knowledge change loud. A changed file that maps to
   no module should be reported as `UNATTRIBUTED`, not silently dropped. Silent
   dropping turns a false clean into a green tick, which is worse than an error.

## 5. The step registry is the knowledge tree's blind spot

A contract is prose in the knowledge tree, but it only executes if
`contracts/run.mjs` contains a regex that matches its lines. CT-004 needed four
new step definitions before it could run at all. Before I wrote them, the
knowledge-only commit failed like this:

```
FAIL  CT-004  Address book limit  (0/5)
        the twentieth address is accepted: no step definition matches: And the customer already has 19 addresses
```

`contracts/run.mjs` is neither knowledge nor module code. `validate.mjs` never
reads it, `impact.mjs` never names it, `drift.mjs` ignores it (see finding 4),
and no lock file records its state. It is also the file that decides what
"rejected" means: my step defines it as HTTP 409. Someone could weaken that
assertion to accept 200 and every tool in this methodology would stay green,
while the skills' loudest hard rule, "never edit a contract to make a build
pass", would technically not have been broken.

A second, smaller trap in the same file: steps are matched by regex only and the
Given/When/Then keyword is ignored. `Given the customer has 20 addresses` binds
to the existing **assertion** `the customer has (\d+) addresses` and fails as a
setup step. I had to phrase my setup as "already has 20 addresses" to dodge my
own assertion. Nothing warns you; the failure looks like a bug in the
implementation.

**Fix:** name the runner in the skills as part of the verification surface, say
that a new contract usually requires new step definitions and that they must be
reviewed alongside the contract, and warn that step matching ignores the
keyword.

## 6. Nothing checks whether a contract scenario has teeth

After both stacks passed, I set the limit to 999 in each implementation and
reran, to see whether CT-004 was actually load-bearing:

```
FAIL  CT-004  Address book limit  (3/5)
22/24 scenarios passed across 5 contracts
```

Two of my five scenarios caught it. The other three ("the twentieth address is
accepted", "removing an address frees a slot", "the limit is per customer") pass
perfectly against an implementation that has no limit at all, because they
assert the permissive side of the rule.

That is not a defect in those scenarios, they are worth having, but nothing in
the tooling can tell the difference. `validate.mjs` says "OK, 0 warnings",
`debt.mjs` reports Traceability 83% and counts BR-011 as fully verified. A
contract file containing five scenarios that assert nothing at all would score
identically. Traceability answers "does a contract exist", not "is the rule
verified", and the `verify` skill presents it as the latter.

**Fix:** a `regen-mutate` mode, or at minimum a line in `knowledge-delta`:
"state which scenario fails if this rule is deleted from the implementation, and
check it". It took me 40 seconds to run and it is the only evidence in this
whole exercise that the new contract does anything.

## 7. A precondition that can never be satisfied, with no escape hatch

`regenerate` lists four preconditions and says "stop and say so if any fails".
The fourth is:

> The knowledge delta has been reviewed by a human, not just written by you

In an agent-run loop, this is unsatisfiable by construction. The literal
instruction is therefore "stop forever". I did not stop, because the task said
to keep going, and I suspect every agent that ever reads this skill will do the
same silently, which is the worst of both worlds: a gate that is always claimed
and never enforced.

**Fix:** give it a real path. Either "if no review has happened, proceed and mark
the delta unreviewed in the report and in the PR body", or make it enforceable,
for example a `Reviewed-by:` trailer on the knowledge commit that the tooling
checks. An unenforceable gate teaches people to ignore gates.

## 8. Ambiguity is only findable by implementing, which the loop forbids first

`knowledge-delta` ends with "do not implement" and offers this test for a good
delta: a colleague who has not seen the task could read only the changed
knowledge files and correctly predict how the system will behave.

My delta passed that test and was still wrong twice, and both only surfaced when
I sat down to build from it:

- **CT-004 scenarios 3 and 4 filled the address book to 19 and then called the
  next add "the twenty-first".** Arithmetic. Reviewable in principle, missed in
  practice, and the validator cannot see it because scenario prose is not
  checked against anything.
- **BR-011 said nothing about precedence.** If a request is at the limit *and*
  has an empty line, is it 400 or 409? The rule was silent, so both
  implementations would have been free to differ, and CT-004 would not have
  noticed.

I fixed both in a second knowledge commit before writing any code, which I think
is the methodology working rather than failing. But no skill says this is
expected. Read literally, the loop is knowledge, then code, once. Read honestly,
it is knowledge, code-attempt, knowledge again, code. The skills should say so,
because a practitioner who hits this on their first change will read it as
having done the process wrong.

## 9. Item-level traceability hides clause-level debt

BR-011 is six paragraphs. CT-004 verifies two of its claims with teeth (finding
6). These claims have no scenario at all:

- the limit does not apply to `PATCH`
- deleted customers are subject to it like anyone else (ASM-001)
- the precedence sentence added in the second knowledge commit
- "no code, no count, no remaining-slots figure" is checked only for the digit
  case, by a regex I wrote myself in the runner

The validator prints `OK. 0 warnings.` and the debt report counts BR-011 as
verified. The unit of traceability is the item, but the unit of behaviour is the
sentence, and a six-paragraph rule with one scenario scores the same as a
one-sentence rule with six.

**Fix:** no clean answer, but the honest minimum is for `verify` to stop
describing Traceability as "active rules with both a verifying contract and an
implementing module" in a way that reads as coverage. It is a link check.

## 10. The lock file made me write something untrue

`regenerate` step 7 says to set, for each regenerated module:

```yaml
generated_by: <your model id>
generated_at: <YYYY-MM-DD>
```

I changed six lines of an implementation that `claude-fable-5` generated on
2026-07-31. Following the instruction literally, the lock now claims
`generated_by: claude-opus-5, generated_at: 2026-08-06`, which reads as "this
whole implementation was generated by Opus today". It was not. The previous
generation's provenance is gone, and the only reason the Regenerability metric
did not also become a fiction is that `last_regeneration` is a separate block
which I deliberately left alone.

**Fix:** split the field. `generated_by` is provenance and should change only on
an actual regeneration; add `last_touched_by` for targeted changes. Until then,
`regenerate` should say "do not rewrite `generated_by` for a partial change".

A related trap in the same step: it says `knowledge_version: <git rev-parse
--short HEAD>`. At the point you update the lock, HEAD is your *code* commit
(here `5be4d92`), not the knowledge commit (`ed6808a`). Following it literally
writes the wrong hash, and `debt.mjs` freshness, which compares against
`git log -1 --format=%h -- <module>/knowledge`, would then report the module
stale forever. I knew to use the knowledge commit; the skill does not say so.

## 11. Assorted smaller annoyances

- **No ID allocation guidance anywhere.** `knowledge-delta` says only "unique
  repository-wide". This repo's de facto convention is `BR-00x` for `customer`
  and `BR-01x` for `orders`. BR-011 is a customer rule sitting in the middle of
  the orders range. Nobody told me, and no tool will ever tell me.
- **`knowledge-delta` step 6 duplicates the whole `impact` skill.** I ran the
  same analysis twice and got identical output. Two skills, one responsibility.
- **The knowledge-only commit is red by construction.** CI runs `node
  verify.mjs` on every commit in a PR. Commit 1 adds CT-004 with no
  implementation, so it fails 5 scenarios. This is the direct consequence of the
  methodology's central discipline, and neither the skills nor the CI config
  acknowledges it. At minimum, the workflow should treat "contracts failing only
  for rules whose implementation is pending" differently, or the skills should
  tell you to expect the red and why it is correct.
- **The README advertises 17/17 scenarios.** It was 19/19 before this change and
  is 24/24 after. Nothing checks numbers in prose against reality, in a
  repository whose thesis is that documentation rots when nothing checks it.
- **Abbreviated hashes are compared as strings.** `debt.mjs` matches the lock's
  `knowledge_version` against `%h`. Seven characters here, but git abbreviates
  longer in bigger repos, and freshness would then report stale permanently.

---

## What was genuinely worth it

A friction log that only complains is not evidence, so, specifically:

1. **Writing the contract before the code caught my own mistake.** The scenario
   arithmetic error in finding 8 was mine, in the specification, before any code
   existed. Writing `if (held.length >= 20) return 409` first would have shipped
   a correct implementation of a rule I had not finished thinking about, and the
   "removing an address frees a slot" question, which is the only genuinely
   interesting part of this rule, would never have come up.

2. **Reading the affected knowledge first surfaced a direct contradiction.**
   BR-002 opened with "A customer may register any number of addresses". A
   code-first change would have left that sentence sitting in the tree,
   contradicting the running system, waiting to mislead the next reader or the
   next regeneration. I would not have opened that file if I were just adding a
   length check. This is the single most valuable instruction in
   `knowledge-delta` and it cost about 8 minutes.

3. **ASM-001 is the best artifact this exercise produced.** Three product
   questions nobody asked (is 20 configurable, does it apply to deleted
   customers, what happens to existing over-limit customers) are now written
   down instead of being decided silently inside an implementation. That file
   will outlive both servers.

4. **`impact.mjs` was fast and correct.** 200ms to establish that `orders` is
   untouched, with the reasons printed. Reasoning about it by hand would have
   taken minutes and left me less certain. When the impact skill says do not
   reason about blast radius yourself, it is right.

5. **One suite, two stacks, no extra test writing.** The Python implementation
   was verified by the same five scenarios with zero additional work. That claim
   in the README holds up.

6. **The lock and debt machinery did catch something.** Freshness went 0% to 50%
   as I updated the customer locks, and it correctly still reports `orders`
   stale, which is real pre-existing debt that predates this branch.

## Was it slower than just writing the code?

Yes, substantially, and it is worth being precise about where the time went.
These are rough working times for this session:

| Phase | Time | Would a code-first change have paid it? |
|---|---|---|
| Reading five skills, finding and reading five tools | ~15 min | No. Most of this was forced by finding 1 |
| Reading the customer and orders knowledge packages | ~8 min | Partly. I would have skimmed BR-002 |
| Writing BR-011, ASM-001, CT-004, OpenAPI, overview | ~20 min | No |
| Implementing in both stacks | ~4 min | Yes, this is the actual work |
| Adding four step definitions to the runner | ~10 min | Yes, some test setup is unavoidable |
| Running tools, locks, four commits | ~10 min | Mostly no |
| **Total** | **~65 min** | |

Writing the check directly, with one test per stack, is about 8 minutes of work.
So the loop cost roughly **8x** on this change. A second change of the same
shape, with the tooling paths known, the runner already carrying the steps, and
no need to re-read the skills, would be about 20 minutes, so **2 to 3x**.

The honest read is that the multiplier is dominated by fixed costs (findings 1
and 2 alone are 20 minutes of pure tooling friction that a working `npx` would
erase) and by artifacts with a long half-life (ASM-001, CT-004). The per-change
marginal cost of the methodology is not 8x. But a first-time reader following
these skills will experience 8x, and they will blame the methodology rather than
the missing npm package.

## Proposed improvements, in priority order

1. **Fix the commands in all five skills.** Replace `npx regen-*` with the
   resolution block this repository's CI already uses, and delete the npx form
   until the package is actually published. Right now the instructions do not
   work and would execute a stranger's code if someone squatted the name.
   (Finding 1)

2. **Give `drift.mjs` a real module-to-code mapping.** Add `generated_paths:` to
   the lock schema, use it before falling back to directory layout, and report
   any changed non-knowledge file that maps to no module as `UNATTRIBUTED`
   rather than dropping it. A drift check that returns clean for a diff that
   rewrites both implementations is worse than no drift check, because it is
   reported as a pass. (Finding 4)

3. **Add a teeth check for contracts.** `regen-mutate <BR-id>`, or at minimum a
   required line in `knowledge-delta`: name the scenario that fails when the
   rule is removed, and run it. Three of my five scenarios pass against an
   implementation with no limit at all, and no existing metric can see that.
   (Finding 6)

4. **Make `contracts/run.mjs` a first-class part of the methodology.** The
   skills should name the step registry, say that new contracts usually need new
   step definitions, require them to be reviewed with the contract, and note
   that step matching ignores Given/When/Then. As it stands, the file that
   defines what every contract *means* is invisible to every tool.
   (Finding 5)

5. **Fix `regenerate` step 7.** `knowledge_version` is `git log -1 --format=%h
   -- <module>/knowledge`, not `git rev-parse --short HEAD`. Do not overwrite
   `generated_by` for a targeted change; add `last_touched_by` to the schema for
   that. (Finding 10)

6. **Give precondition 4 an escape hatch, and say the loop iterates.** Human
   review cannot be satisfied inside an agent run, and knowledge is routinely
   corrected once implementation starts. Both are normal. The skills currently
   describe a straight line and hand the practitioner an unsatisfiable stop
   condition halfway down it. (Findings 7 and 8)

---

*Recorded while doing the work, not reconstructed afterwards. Branch
`feature/address-limit`, four commits, knowledge before code, both stacks green.*
