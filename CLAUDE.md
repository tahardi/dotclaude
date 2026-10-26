# Coding

When working in a git repository always use a git worktree to complete work. Place the worktree under the `~/Documents/code/wts/` directory, where the worktree naming convention is `repo-cardname-description`. For example, if you were working on the `bearclave/` repo on card BCL-55 to add an attestation module for the AWS Nitro platform you would create the worktree `~/Documents/code/wts/bearclave-bcl-55-nitro-attestation-module/`. Never make changes to main|master.

When titling a PR use the format `[ABC-YYYY] Card Title`, where `ABC` is the project tag used by Jira and `YYYY` is the card number. For example, if you were working on BCL-55 "Nitro Attestation Module" you would title the PR `[BCL-55] Nitro Attestation Module`. If there is no associated card, come up with a concise title to describe the PR.

## Coding Style & Conventions

The rules in this introduction section should apply to **ALL** languages.

1. **NEVER** add comment to code. I will explicitly ask you to add comments where necessary. Otherwise, assume I do not want any comments on code you create or modify.
2. Try to limit line length to 120 characters. If a function declaration, or call, exceeds the line length then make it multi-line with one argument per line.
3. Try to keep files singularly focused because I find it difficult to parse when there are multiple interface or type definitions in a file. Keeping files focused on one subject is easier to read and generally makes them shorter as well.

### Golang

1. Default to standard Go if there is ever a question about style or convention
2. Error messages should be present tense (generally starting with "ing" verbs)
3. Go test names should use the format `TestMethod` or `TestType_Method`, where the first is for standalone methods and the second is for methods defined on types.
4. You should put all test cases for a given method in a single `TestMethod` or `TestType_Method` function.
5. You should use table driven tests whenever possible. If not, use `t.Run("happy path - scenario")` or `t.Run("error - scenario")` to enumerate test cases.
6. You should use the "given, when, then" model for splitting up the three difference sections of a test, where each section is preceded by a comment (e.g., `// given` above test setup, `// want` above the call under test)

### Makefile

1. When a recipe command has several flags, put the command on the first line, then one flag (with its value) or argument per line, each line ending with `\`. Short commands like `mkdir -p dir` stay on one line. For example:

```make
git clone \
    --depth 1 \
    --branch $(whisper_version) \
    https://github.com/ggml-org/whisper.cpp \
    $(whisper_src)
```

# Writing Style

Be as clear as possible while also being as concise as possible. I prefer plain English over technical jargon. Avoid variable, function, and file names in prose unless they're the actual subject. No filler or restating my request back to me. This applies to code comments, PR descriptions, and every response.
