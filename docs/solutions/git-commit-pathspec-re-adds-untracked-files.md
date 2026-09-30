---
title: "`git rm --cached` then `git commit -- <path>` silently re-tracks the files"
date: 2026-09-27
tags: [git, copyright, data-hygiene, commits, folio-insights]
severity: high
area: repository hygiene
symptom: "Commit message says a corpus was untracked, but `git ls-tree -r HEAD -- output/test1` still lists every file"
---

## Problem

The `test1` corpus (`output/test1/`) held the full text of a copyrighted book and had been on public `master` since 2026-04-12. The fix ran `git rm -r --cached output/test1` (untrack, keep the files on disk), edited `.gitignore`/`.dockerignore`, and committed with an explicit path list:

```bash
git commit -m "..." -- .gitignore .dockerignore Dockerfile.web output/test1
```

The commit reported only the three config files. `output/test1` was still tracked, and a code reviewer caught it: `git ls-tree -r HEAD -- output/test1` listed all 20 files.

## Root cause

`git commit -- <pathspec>` is `--only` mode: it stages the **working-tree** state of every named path, ignoring what the index says. The files were still on disk, so naming `output/test1` re-added them and undid the `git rm --cached`. A deletion staged with `--cached` survives only a commit that does not name the path.

The "name your paths on every commit" habit (used here to keep unrelated staged work out of a commit) is exactly what triggers it.

## Fix

Untrack, then commit the index as staged, without naming the untracked paths:

```bash
git rm -r --cached output/test1
git diff --cached --name-only   # confirm only the intended deletions are staged
git commit -m "..."             # no pathspec
git ls-tree -r --name-only HEAD -- output/test1 | wc -l   # must print 0
```

## Prevention

- After any untrack commit, verify with `git ls-tree -r HEAD -- <path>` rather than trusting the commit's file count.
- When the working tree still holds the files, never pass their paths to `git commit --`. Deleting the files outright (`git rm`, not `--cached`) would also be safe with a pathspec, but loses the local copy.
- Removing a file from the current tree does not remove it from history; a copyrighted or secret file on a public branch also needs a history rewrite (`git filter-repo --invert-paths`) and a force-push.
