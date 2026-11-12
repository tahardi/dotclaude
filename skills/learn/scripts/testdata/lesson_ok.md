---
class: command-injection
status: to-learn
comfortable: false
grades: []
---

# Command injection

## Lesson

### What it is

Command injection happens when a program builds a shell command from text it did not write itself.

### How an attack works

An attacker who controls a branch name gets it into the command line, and the shell runs whatever follows a `;`.

### Trace

```maple-trace
{"lang":"typescript","code":"import { exec } from 'node:child_process'\n\nexport function checkout(branch: string) {\n  exec(`git checkout ${branch}`)\n}","steps":[{"lines":[3,3],"text":"The branch name arrives from the pull request."},{"lines":[4,4],"text":"The name goes into a shell string, so `main; rm -rf ~` runs two commands."}]}
```

### Quiz

```maple-quiz
{"questions":[{"question":"What makes command injection possible?","choices":["Building a shell string from untrusted text","Using git","Long branch names"],"answer":0,"why":"The shell reads the text as code."},{"question":"Which call avoids the shell?","choices":["exec","execFile with an argument list"],"answer":1,"why":"execFile passes each argument to the program as is."},{"question":"Who is the attacker here?","choices":["Anyone who can name a branch","Only the repo owner"],"answer":0,"why":"Branch names come from anyone who opens a pull request."}]}
```

## Findings

### 2026-11-12 MPL-340 F3: Branch name reaches the shell
- PR: https://github.com/example/repo/pull/1
- Code: `src/git.ts:4`

The branch name goes into a shell string, the classic shape of command injection. Passing it to execFile as one argument defends it here.
