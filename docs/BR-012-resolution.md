# BR-012: rejected, and why

A simulated 2am hotfix capped the address list response at the fifty most
recently added addresses, to stop a page timing out for "a customer with
thousands of addresses". Reconciliation drafted BR-012 to describe it, marked
draft and explicitly not agreed, which is the correct behaviour.

Reviewing that draft against its neighbours settles it: **BR-011 already caps a
customer at twenty addresses.** A fifty-item response cap on a twenty-item
maximum can never fire. The hotfix defended against a state the knowledge
already forbids, so it was dead code from the moment it was written.

There is a sharper reason to reject it than mere redundancy. The list is
ordered oldest first and the cap kept the last fifty, so had the limit ever been
raised above fifty, the address most reliably dropped would have been the
customer's default, returning a list with no default at all. CT-002 would have
passed throughout, because it never asks for more addresses than the cap.

**Resolution: BR-012 retired, truncation removed from both implementations.**

What this exercise demonstrates is not that the tooling caught a contradiction.
It did not. Validation reported `OK. 0 warnings.` on a tree containing a draft
rule that contradicted an active one, because every file was individually well
formed, and the contract suite stayed green throughout. Structural tooling
detects that knowledge is missing. It cannot detect that knowledge is wrong.
A person reading two rules side by side is still the only thing that closes
that gap.
