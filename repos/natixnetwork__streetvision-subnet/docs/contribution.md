# Contributing to NATIX Subnet

We're excited to have you here. This guide covers everything you need to contribute effectively — from setting up your fork to getting a PR merged.

---

## Getting started

1. **Browse open issues** at [GitHub Issues](https://github.com/natixnetwork/natix-subnet/issues) to find something to work on.

2. **Fork and clone:**
   ```bash
   git clone https://github.com/your-username/natix-subnet.git
   cd natix-subnet
   git remote add upstream https://github.com/natixnetwork/natix-subnet.git
   ```

3. **Sync your fork** before starting any work:
   ```bash
   git fetch upstream
   git checkout development
   git merge upstream/development
   ```

4. **Create a branch** off `development`:
   ```bash
   git checkout -b feature/42/add-new-detection-model
   ```
   See [workflow.md](workflow.md) for branch naming conventions.

5. **Set up your environment** — see [workflow.md](workflow.md) for install and run instructions.

---

## Making changes

- Follow PEP 8. Format with `black` before committing.
- Write tests for any new or modified functionality.
- Keep commits focused: one logical change per commit.
- Write commit messages in imperative mood, subject line under 50 characters:
  ```
  Add ViT detector support for roadwork classification
  ```

---

## Submitting a PR

**Before opening the PR:**
- Ensure all tests pass: `pytest tests/`
- Ensure linting is clean: `flake8 natix/ neurons/`
- If you have multiple fixup commits, squash them (see [Squashing commits](#squashing-commits) below).

**PR standards:**
- One PR, one concern — feature, bug fix, or refactor, not a mixture.
- Fewer than 50 files changed; split large changes into smaller related PRs.
- New features must include tests. Bug fixes should include a test that demonstrates the bug.
- Update relevant documentation when behaviour changes.
- Add GitHub labels to categorize the PR.

**After opening the PR:**
- Verify all status checks pass.
- Respond promptly to review comments — unanswered PRs may be closed.
- If the changes are not ready for merge but you want early feedback, open a draft PR.

---

## Code review

We use the following language in PR comments:

- **ACK** — "I have tested the code and agree it should be merged"
- **utACK** — "I have not tested the code, but I have reviewed it and it looks OK"
- **Concept ACK** — "I agree with the general goal of this PR"
- **NACK** — "I disagree this should be merged" (must include technical justification)
- **nit** — a trivial, non-blocking issue

Reviewers should include the commit hash they reviewed. For a more detailed description of the review process, see [code-review.md](code-review.md).

---

## Addressing feedback

Add new commits in response to review rather than amending. Push the new commits to the same branch — reviewers can see the delta. If you disagree with feedback, explain your reasoning in a reply; don't silently ignore it.

---

## Squashing commits

If your branch has fixup commits or excessively fine-grained history, squash before the PR is merged:

```bash
git checkout your-branch
git rebase -i HEAD~n   # n = number of commits to squash
# mark all but the first as 'squash', then edit the combined message
git push --force-with-lease
```

---

## Refactoring PRs

Refactoring PRs should:
- Not mix code moves, style fixes, and logic changes in one PR.
- Not change observable behaviour (bugs must be preserved as-is and fixed separately).
- Be short and easy to verify — maintainers aim for quick turnaround on clean refactors.

New contributors should avoid large refactoring PRs until they have established familiarity with the codebase.

---

## Bug reports

Please file bugs as GitHub issues. Include:

- A clear, descriptive title.
- Exact steps to reproduce (commands run, config used).
- What you expected vs. what happened.
- Bittensor subnet version and commit hash (`git log -1`).
- OS and Python version.
- Relevant logs or stack traces in a code block.

---

## Feature suggestions

Open a GitHub issue with:
- A clear title and step-by-step description of the proposed behaviour.
- Why this would be useful to most users.
- Any examples or prior art from other projects.

---

## Code of Conduct

All contributors are expected to follow the [Code of Conduct](code-of-conduct.md).
