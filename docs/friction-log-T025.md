# Friction log: running the reconciliation loop on a hotfix

**Task T-025.** A deliberately realistic 2am hotfix, committed to
`exercise/reconcile` as implementation only, then taken through `/drift-check`
and `/reconcile` exactly as the published skill files describe them.

The hotfix: `GET /customers/{id}/addresses` capped at the 50 most recent, in
both stacks, one commit, no knowledge touched.

```
30d52e6  Hotfix: cap address list response to stop page timeouts
```

Outcome, stated up front because it is the finding rather than the footnote:

| Check | Result |
|---|---|
| `drift.mjs --tree . --base main` | **No code-ahead drift** (exit 0) |
| `validate.mjs .` | OK, 0 warnings |
| `debt.mjs .` | Integrity **clean, 0 code-ahead** |
| `verify.mjs` (both stacks) | **24/24 across 5 contracts, all green** |

Every automated check in this repository passed on a change that silently
truncates an API response and can make the default address vanish from the only
endpoint that exposes it. Nothing below is hypothetical; every command and its
output is quoted verbatim.

---

## 1. What drift-check actually caught: nothing

The skill's mechanical rule is sound. The tool that implements it could not see
the change at all.

```
$ git diff --name-only main...HEAD
impl/python/server.py
impl/typescript/server.mjs

$ node ../regen-engineering-schema/tools/drift.mjs --tree . --base main
Drift check  /Users/tyson/Dropbox/codes/regen-engineering-demo
2 changed file(s), 0 module(s) touched

No code-ahead drift. Every module with implementation changes also changed its knowledge.
exit=0
```

Read the second line again. **Two files changed, zero modules touched.** The
tool announced that it had understood nothing, and then, in the next sentence,
reported a clean result in the confident voice reserved for a real answer.

The cause is in the partition step of `drift.mjs`:

```js
if (tree.modules.has(parts[0])) touch(parts[0], 'code', path)
```

A module is a directory containing `knowledge/`, so this repository's modules
are `customer` and `orders`. Its implementations live in `impl/typescript/` and
`impl/python/`. `impl` is not a module, so both changed files fall off the end
of the loop and are discarded without comment. The verdict loop then iterates an
empty map and prints the success message.

The rule works when the layout matches. Control test, same tool, same tree, one
invented path:

```
$ node .../drift.mjs --tree . --changed customer/src/server.mjs
1 changed file(s), 1 module(s) touched

DRIFT     customer: implementation changed, knowledge did not
FAILED: 1 module(s) with code-ahead drift.
exit=1
```

So this is not a broken rule, it is an unstated layout assumption. The schema's
own `example/` tree has no implementation files at all, so the assumption is
never exercised, and the reference demo, which is the artifact people are
pointed at, violates it.

There is a second wrinkle that a path-mapping config alone would not fix. In
this repository **one file implements two modules**: `impl/typescript/server.mjs`
serves the `customer` routes and the `orders` routes. Any fix has to map
implementation paths to modules many-to-many, not one-to-one, and has to decide
whether touching a shared file means both modules drifted.

### Would it have caught it on a real merge to main?

No, twice over, and the second reason is worse than the first.

**First**, per the above, it does not fire on this repository's layout.

**Second**, and independently: `drift.mjs` **does not run in CI at all.**

```
$ grep -n "drift" .github/workflows/*.yml verify.mjs contracts/run.mjs
(no output)
```

`verify.yml` has a `knowledge` job that runs `validate.mjs`, `impact.mjs` and
`graph.mjs`. Drift is not among them. So even after the path bug is fixed, a
hotfix merged to `main` would be checked by nobody unless a reviewer happened to
run the tool by hand. A drift check that lives only in a skill file is a check
that runs when someone is already suspicious, which is the one situation where
it was not needed.

The contract suite would not have saved it either. All 24 scenarios use a
handful of addresses, so a 50-item cap is invisible to every one of them, and
`CT-002`, the contract that exists specifically to protect the default-address
invariant, passes while the invariant is breakable.

### The one check that did fire, and why that is not a consolation

`debt.mjs` went from `Integrity clean, 0 code-ahead` to:

```
Integrity     ....................  2 code-ahead
                 customer (python): code-ahead since 2026-08-06, hotfix 30d52e6 ...
                 customer (typescript): code-ahead since 2026-08-06, hotfix 30d52e6 ...
```

It fired because **I typed the `drift_debt` block into the two lock files by
hand.** `debt.mjs` reads declared drift; it does not detect it. Integrity is a
self-report. A team that never declares drift has a permanently clean integrity
score, and the metric is at its most reassuring exactly when it is least earned.

---

## 2. Did the reconciliation classify rule vs incidental detail correctly?

Mostly yes, and the classification step is the part of the skill that carried
its weight. The four buckets in step 3 (behaviour / decision / assumption /
incidental) did real work.

**Promoted to a rule** (`BR-012`, draft): the cap itself; that it selects the
most recently *added* fifty; that the fifty stay in oldest-first order; that
nothing in the response indicates truncation; that the omitted addresses stay
reachable by id through `PATCH` and `DELETE`. All of these are distinguishable
by a caller, which is the skill's test, and I checked each against the code
rather than assuming.

**Promoted to an assumption** (`ASM-002`, draft): that the address count caused
the timeout; that fifty suffices; that silent truncation beats failing; that
customers holding more than fifty exist at all.

**Refused promotion**: `.slice(-50)` versus `[-50:]`, the literal sitting inline
rather than in a named constant next to `ADDRESS_LIMIT`, the sort-then-slice
ordering, the in-memory store. None of these are observable and none appear in
the delta.

**Refused a decision record.** The skill's third bucket is "a choice between
real alternatives becomes a decision, with the alternatives that lost". The
temptation here was strong, because pagination, a total count, a `413` and a
`truncated` flag are all obvious alternatives and an ADR listing them would have
looked professional. But nothing in the diff or the commit message shows any of
them was weighed. Writing that ADR would have manufactured deliberation, which
is precisely the laundering the skill warns against, just wearing a different
hat. The alternatives are recorded in `ASM-002` as things that *were not*
considered. I think this is the single best decision in the delta and it was
prompted by the skill, not by me.

One classification I am less sure of. The most important consequence of the
change, that the default address can be absent from the list, is **not** in
`BR-012`; it is in `ISS-002`. Arguably it is behaviour and belongs in the rule.
I put it in the issue because it is not behaviour anyone intends, and writing it
into a rule would read as specifying it. The skill gives no guidance on where a
discovered defect goes when it is a consequence of the drifted behaviour rather
than the behaviour itself, and I made that call unaided.

---

## 3. The failure mode: did I invent justification the diff does not support?

**Yes. Twice, and the first one was a plain factual error about a system I had
just read.**

This section is the reason the log exists, so the offending text is quoted
before it is excused.

### Invention 1: an imagined production architecture

First draft of `ASM-002`, item 1:

> Serialising a few thousand small objects is not obviously slow, so the cause
> may equally have been **a query, an N+1 in the page that consumes this list**,
> or something unrelated that happened at the same time.

There is no query. There is no N+1. There is no datastore:

```
$ grep -rniE "sql|database|query|postgres|sqlite" impl/typescript/server.mjs impl/python/server.py
(no output)

impl/typescript/server.mjs:4:  // Storage is in memory: persistence would add plumbing ...
```

I invented a plausible production incident narrative and wrote it into proposed
knowledge as though it were analysis. Note the shape of the failure: I was not
laundering the hotfix into a good decision, I was laundering my *scepticism*
into expertise. The sentence sounds rigorous. It cites a specific failure mode.
It is about a system that does not exist. Had a reviewer accepted the delta, the
repository would have acquired a false belief about its own architecture,
introduced by the very process meant to keep knowledge true.

It was also unforced. The honest version of the same point is shorter and
stronger, because "the code issues no query of any kind, so whatever was slow,
the diff does not show it" is both true and more damning. That is what the file
now says.

### Invention 2: an incident that is not in the record

First draft of `BR-012`:

> Fifty was chosen **during an incident** and is not derived from anything.

The commit says `Hotfix: cap address list response to stop page timeouts` and
that a customer was timing out the page. It names no incident, no ticket, no
time of day. I imported "2am incident" from the framing of the task I was given
and wrote it down as though the artifact said it. Smaller than the first, but
the same mechanism: filling a gap in the evidence with the story I arrived
holding. The file now says the inference is an inference.

### Invention 2b, caught in the same pass

`ASM-002` item 2 originally enumerated callers, "a caller that renders a picker
... a caller that reconciles, exports, counts". Nothing in this repository
identifies any caller. One of the four survived, because `BR-002` really does
contemplate "callers that look addresses up by line rather than id", and one was
retained as an explicit inference from the commit message. The other two were
furniture.

### What this says about the method

Three inventions in three files, all in the same direction: **towards a richer
story than the evidence carries.** All three survived my own drafting and were
caught only on a deliberate second pass whose entire purpose was to hunt for
them. Without that instruction in the task, all three would have shipped in the
PR.

The `reconcile` skill has one guardrail here, "do not launder an emergency
decision into a considered one", and it is aimed at the optimistic direction
only. It has nothing to say about inventing context, inventing causes, or
inventing callers. That gap matters more for an agent than a human, because the
prose comes out fluent either way and fluency is what gets a delta approved.

I have corrected all three in place rather than leaving them for effect. A
knowledge file is not a place to preserve a known-false sentence, so `ASM-002`
carries a one-line note pointing here instead.

---

## 4. Was reviewing a drafted delta cheaper than writing one from scratch?

I have to be careful, because I did not review a delta, I wrote one. So the
honest answer has two halves, and only one of them is measured.

**Measured, my side.** Producing the delta took roughly 12 tool calls end to
end. The split is the interesting part:

- **~8 calls reading**: `BR-001`, `BR-002`, `BR-003`, `BR-011`, `ASM-001`,
  `CT-002`, `CT-004`, `RISK-001`, `NFR-002`, `overview.md`,
  `api.openapi.yaml`, plus both implementations and the contract runner.
- **3 calls writing** the three files.
- **1 call** for the invention hunt in section 3.

So about 70% of the cost was step 2, "read the module's existing knowledge
first", and it is not optional: every genuinely valuable thing in this delta,
the `BR-002` default-drop, the `BR-011` incoherence, the `ASM-001` cross-check,
came out of reading, not writing. **A reconciliation is a reading task with a
writing task attached.** The skill presents the draft as the deliverable, which
undersells where the effort and the value actually are.

**Estimated, the reviewer's side.** For the human this is aimed at, I would
estimate the saving as **large on the writing and near-total on the recall**.
The delta is about 1,400 words of structured prose that nobody has to compose,
and, more importantly, it contains four cross-references (`BR-002`, `BR-011`,
`ASM-001`, `CT-002`) that a reviewer would have had to remember unprompted at
2am the following morning. Correcting "fifty is arbitrary and here is why it
cannot coexist with twenty" is a five-minute conversation. Producing it from a
blank page requires re-reading the module. Call it 30 to 60 minutes down to
5 to 10, with the bigger win being that the 30-to-60-minute version usually does
not happen at all.

**The caveat that keeps this from being a clean win.** Section 3 showed the
draft carried three confident false statements. A reviewer who trusts the draft
inherits them; the cost only drops if the reviewer reads adversarially, and a
well-formatted delta actively discourages that. The saving is real but it is a
saving *conditional on review quality*, and the skill's framing ("everybody will
correct a wrong sentence about their own domain") assumes the wrong sentence
looks wrong. Invention 1 did not look wrong. It looked like the most competent
sentence in the file.

---

## 5. Who caught the contradiction: tooling, skill, or judgment?

Cleanly separable, and the answer is unflattering to the tooling.

| Finding | Tooling | Skill | Judgment |
|---|---|---|---|
| Implementation changed without knowledge | **no** (false negative) | yes, if run by hand | yes |
| Cap contradicts `BR-011`'s twenty | no | **prompted** | yes |
| Cap contradicts `BR-002` / OpenAPI wording | no | **prompted** | yes |
| Cap can drop the default address | no | no | **only judgment** |
| `ASM-001` point 3 is falsified if the incident was real | no | no | **only judgment** |

**Tooling caught none of it.** `validate.mjs` reported `OK. 0 warnings.` on a
tree containing a draft rule that directly contradicts two active rules in the
same module. That is not a bug; it validates frontmatter, ID uniqueness, link
integrity and the overview-versus-OpenAPI table. Contradiction is not in its
vocabulary. But the output is indistinguishable from the output on a coherent
tree, and "0 warnings" is what a reviewer under time pressure reads.

**The skill caught two of the three, in the sense that mattered.** Step 2, "read
the module's existing knowledge first ... if the code now contradicts an
existing rule, that is the finding: say so loudly", is why I read `BR-011`
before writing anything, and it is why the output is an issue with a rule
attached rather than a rule with a caveat attached. Without that instruction the
likely output was `BR-012` alone, neatly formatted, quietly disagreeing with its
neighbour. That is a genuine save and it is the skill's best moment.

**Judgment alone caught the one that matters most.** No instruction and no tool
pointed at the interaction between `.slice(-50)` and `BR-002`'s promotion rule.
It came from holding two documents in mind at once and noticing that "keep the
newest fifty" and "the oldest address is the default" name the same address from
opposite ends. That is a live defect, not a documentation gap, and it is the
only finding here that would page someone.

The limit is worth stating plainly, because it bounds what this methodology can
promise: **structural tooling detects that knowledge is missing; it cannot
detect that knowledge is wrong.** Everything mechanical here answers "did a file
change". Nothing answers "do these two files describe the same system". Between
those two questions sits every interesting failure.

---

## 6. Concrete improvements

Ordered by how much damage the absence causes. The first three are the ones I
would do this week.

### 1. `drift.mjs` must fail loudly when it cannot map a changed file

This is the highest-value fix in the log, because the current behaviour is not
"missed a finding", it is "produced a false reassurance".

Two changes:

- **Never report success on an empty partition.** When `changed.length > 0` and
  `state.size === 0`, exit non-zero:

  ```
  UNMAPPED  2 changed file(s) belong to no module. Drift cannot be assessed.
            impl/typescript/server.mjs
            impl/python/server.py
  Add an `implements:` mapping to the module lock, or pass --changed explicitly.
  ```

  Say the same thing for partial coverage: `3 of 5 changed files mapped`.

- **Add an explicit implementation mapping,** because inferring it from layout
  is the root cause. In each lock:

  ```yaml
  module: customer
  stack: typescript
  implements:
    - impl/typescript/server.mjs
  ```

  It must be many-to-many: `impl/typescript/server.mjs` implements both
  `customer` and `orders` here. `validate.mjs` should then warn on any
  non-knowledge file claimed by no module, which turns the mapping into
  something that stays true.

Interim, for anyone reading this before the fix lands: `drift.mjs` on this
repository is a no-op. Do not treat a green result as evidence.

### 2. Put drift in CI, and ship the workflow with the schema

`verify.yml`'s `knowledge` job already clones the schema repo and runs three
tools. Adding the fourth is four lines:

```yaml
- name: Drift check
  run: |
    cd /tmp/schema
    node tools/drift.mjs --tree "$GITHUB_WORKSPACE" --base origin/main
```

with `fetch-depth: 0` on the checkout so the base ref exists. The schema repo
has an `action/` directory; drift belongs in it, so consumers get it by default
rather than by remembering. And the `drift-check` skill should open by saying
that if the tool is not wired into CI, the check is advisory only, because a
merge-time check nobody runs at merge time is not a check.

### 3. Give `reconcile` an explicit "unverifiable" branch, and teach the runner about `status: draft`

Step 5 says write a contract "if the new behaviour is checkable" and then stops.
Here the behaviour is **not** checkable, and that fact is the strongest evidence
of the contradiction: `BR-011` caps the book at twenty, so no scenario can build
a customer with fifty-one addresses through the documented API. The skill should
say so explicitly:

> If you cannot write a contract, write down why. If the reason is that the
> system cannot reach the state, that is not a gap in the contract, it is
> evidence the rule is incoherent, and it belongs in the report. Never reach
> around the public API to construct a state the API forbids: a green test for
> an unreachable rule is worse than no test.

There is a matching tooling problem. `contracts/run.mjs` globs every
`contracts/*.md` and ignores frontmatter `status` entirely:

```js
else if (basename(dirname(full)) === 'contracts' && entry.endsWith('.md')) out.push(full)
```

So a contract drafted alongside a draft rule executes immediately and fails the
build, which pressures the author into exactly the two behaviours the
methodology forbids: skip the contract, or edit knowledge until it passes. The
runner should skip `status: draft` unless `--include-draft` is passed, and
report them as `SKIP (draft)` so they are visible rather than absent.

### 4. Add a symmetric warning about inventing context

The skill warns against laundering an emergency into a considered decision. It
should warn, in the same breath, against the mirror image, because section 3 of
this log is three instances of it:

> Do not invent the incident either. Every factual claim in a reconciled delta
> must trace to the diff, the commit message, or existing knowledge. If it
> traces to none of those, mark it as speculation or cut it. Inventing a cause,
> a caller, or an architecture is the same failure as inventing a rationale, and
> it is harder to spot because it reads as diligence.

A practical addition to step 8's report: **list the claims in the delta that
have no source.** Forcing that list is what caught all three of mine.

### 5. Make contradiction a first-class relation

`validate.mjs` cannot see semantic contradiction and should not try to. But it
could see a *declared* one. Add `contradicts: [BR-002, BR-011]` to the
frontmatter schema, and then:

- `graph.mjs` renders contradiction edges in red, so incoherence is visible in
  the diagram the README already publishes;
- `debt.mjs` gains a metric beside Coverage and Integrity:
  `Coherence: 1 unresolved contradiction`;
- `validate.mjs` warns when an `active` item is the target of a `contradicts`
  edge from another `active` item, since two active items cannot both be true.

This does not detect contradiction, it *tracks* it, which is the achievable
half. Today `ISS-002` states the contradiction in prose that no tool reads, and
it will fall out of every dashboard the moment someone closes the issue.

### 6. Rename `debt.mjs`'s Integrity metric to what it measures

`Integrity clean, 0 code-ahead` on a tree with real code-ahead drift is an
actively misleading line. It reports declared drift. Call it
`Declared drift: none (self-reported)`, or compute it from git and make it mean
what it says. As it stands the metric is at its most reassuring precisely when a
team has stopped doing the bookkeeping.

---

## 7. What was deliberately not done

- **The delta is not merged and must not be.** `BR-012` and `ASM-002` are
  `status: draft`. The `reconcile` skill's first hard rule is that a human
  decides whether what the code does is what the system should do, and this is
  the case where those two answers differ.
- **No knowledge was edited to make anything pass.** `BR-002`, `BR-011`,
  `api.openapi.yaml` and `overview.md` are untouched, though all four are now
  partly false. Editing an interface contract so it agrees with a hotfix is how
  a source of truth stops being one.
- **The hotfix was not reverted**, although `ISS-002` argues that a revert is
  the likely correct outcome. Reverting would have made the exercise tidy and
  removed the artifact the reviewer needs to judge.
