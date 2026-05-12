# Code Review Guidelines

## Conceptual review

A review may begin as a conceptual review, where the reviewer leaves one of:

- `Concept (N)ACK` — "I do (not) agree with the general goal of this pull request"
- `Approach (N)ACK` — implies Concept ACK, but "I do (not) agree with the approach"

A NACK must include a rationale. NACKs without reasoning may be disregarded.

After conceptual agreement, code review proceeds. A review begins with `ACK BRANCH_COMMIT` (the top commit of the PR branch), followed by a description of how the reviewer conducted the review:

- "I have tested the code" — change-specific manual testing in addition to running tests; describe how if not obvious
- "I have not tested the code, but I have reviewed it and it looks OK, I agree it can be merged"
- A **nit** refers to a trivial, often non-blocking issue

## Reviewer weight

Project maintainers weigh peer reviewer opinions using common sense judgement. Reviewers with deeper commitment to the project or clear domain expertise will naturally carry more weight.

Consensus-critical code changes require a higher bar for discussion and peer review — mistakes can be costly to the network. Refactoring of consensus-critical code is held to the same standard.

## Finding reviewers

The review process can be lengthy. If your PR has been waiting for attention:

- **Feature freeze** — during release preparation, only bug fixes are prioritised. If your PR adds a feature, wait for the release to cut.
- **Lack of interest** — silence often signals mild widespread dislike more than nits do. Take another look: is the change too broad? does it adhere to the [workflow](workflow.md)? is it clearly written? Refine and re-ask for feedback.
- **Complexity** — use [Git Blame](https://docs.github.com/en/github/managing-files-in-a-repository/managing-files-on-github/tracking-changes-in-a-file) to find who last touched the code you're changing and ask them directly. Don't be incessant.
- **Long wait with no signal** — after a month with no activity on a small, clean PR, it is reasonable to ask for a look on Discord. Return the favour by reviewing others.
