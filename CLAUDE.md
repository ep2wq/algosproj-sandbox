Make ep2wq the only author and contributor in all three repos (algosproj-frontend, algosproj-backend, algosproj-sandbox). Don't change any code.

1. Identity. In each repo, set the local git config: user.name "ep2wq" and user.email "<EMAIL>". Use git config (without --global).

2. Stop adding Claude as a co-author in future commits.
   - Create or update AlgosProj/.claude/settings.json so commits and PRs have no attribution. Check which setting this version of Claude Code supports: the "attribution" setting with empty "commit" and "pr" strings, or "includeCoAuthoredBy": false. Keep any existing settings in that file.
   - Also add this rule to the "Working rules" section of each repo's CLAUDE.md: "Never add Co-Authored-By or Claude-Session lines, or any other attribution, to commit messages or PR descriptions. ep2wq is the only author."

3. Existing commits. For each repo, run git log --format="%h | %an <%ae> | %s" and git status -sb. If the branch has already been pushed (it tracks origin/main and is not ahead of it, or origin/main exists), do NOT rewrite anything in that repo. Tell me and move on. For repos with unpushed commits only:
   - Rewrite all commits so the author and committer are ep2wq <EMAIL>.
   - Remove every line starting with "Co-Authored-By:" or "Claude-Session:" from the commit messages, plus any blank line left at the end of a message.
   Use whatever works on this machine (git filter-branch with --env-filter and --msg-filter, or git rebase --root with --exec). Make a backup branch first (git branch backup-before-rewrite) and tell me its name.

4. Verify. For each repo show git log --format="%h | %an <%ae> | %cn <%ce> | %s", and run a search of the full commit messages for "co-authored" and "claude" (git log --format=%B and findstr /i). Both must be clean: every commit shows ep2wq, and the search finds nothing.

Don't push and don't force-push anything. When done, summarize per repo: rewritten, skipped (already pushed), or already clean.
# CLAUDE.md

## Project overview

AlgosProj is an interactive learning platform for data structures and algorithms.
Students read a lesson, watch a visualization, write code in the browser (Python, Java,
JavaScript or C++), and the code is run against test cases. Passing earns points on a leaderboard.
An AI tutor gives hints.

Three separate repos, three separate deployments:

- **algosproj-frontend**: React + TypeScript + Vite + Tailwind v4. Talks only to the backend.
- **algosproj-backend**: Laravel API. Handles auth (Sanctum tokens), lessons, problems,
  submissions, points and the leaderboard. It is the only service that calls the sandbox.
- **algosproj-sandbox**: FastAPI service that runs user code in throwaway Docker containers
  and returns the results. Never exposed to the public internet; the backend calls it with
  a shared secret.

Flow: frontend -> backend -> sandbox. The frontend never calls the sandbox directly.

Points and completions are only awarded after the sandbox grades a submission
server-side. Never trust a score sent by the client.

## This repo

- Stack: Python, FastAPI, Docker SDK for Python. Dependencies are only fastapi, uvicorn,
  docker and pytest.
- Layout: `app/main.py` (API, secret check, request limits), `app/sandbox.py` (container
  settings, maps runner output to the API response), `runner/` (the `algosproj-runner`
  image: `Dockerfile` and `runner.py`), `tests/test_sandbox.py`.
- Each submission runs in its own container, destroyed afterward. Every container must
  have: no network, 256 MB memory with swap equal to memory, a pids limit of 64, one CPU,
  user `nobody` with all capabilities dropped and `no-new-privileges`, and a read-only
  filesystem apart from an exec-enabled 64 MB tmpfs at `/tmp`. Timeouts: 30 s compile,
  3 s per test, 40 s for the whole container.
- One runner image holds every language. `runner.py` has the language table, reads the
  submission from the `SUBMISSION` env var (base64 JSON) and prints exactly one JSON
  object. Its output format is the same for every language, so adding a language means
  adding a row to its table, the package to the Dockerfile and the name to
  `sandbox.LANGUAGES`, without changing the API.

  | Language     | Source file | Compile                               | Run                           |
  |--------------|-------------|---------------------------------------|-------------------------------|
  | `python`     | `main.py`   | none                                  | `python3 main.py`             |
  | `java`       | `Main.java` | `javac Main.java`                     | `java -Xmx128m -Xss512k Main` |
  | `javascript` | `main.js`   | none                                  | `node main.js`                |
  | `cpp`        | `main.cpp`  | `g++ -O2 -std=c++17 -o main main.cpp` | `./main`                      |

- Java submissions must declare `public class Main`; the file is always `Main.java`.
- `runner.py` must stay PID 1 in the container: after each program run it kills every
  other process (`kill(-1)`) and reaps zombies, and it makes itself non-dumpable so user
  code can't read the expected outputs from `/proc/1/environ`.
- Reject any request that doesn't carry the shared secret in the `X-Sandbox-Secret` header.
- Commands:
  - Build the image (again after any change in `runner/`): `docker build -t algosproj-runner runner`
  - Run: `python -m venv venv`, `pip install -r requirements.txt`, copy `.env.example`
    to `.env`, `uvicorn app.main:app --reload --port 8001`
  - Test (needs Docker running and the image built): `python -m pytest tests -v`
  - `Dockerfile` builds the API image (`docker build -t algosproj-sandbox .`), for local dev only; see README "Docker".

## Working rules

- Keep code simple. Don't add abstractions, patterns or dependencies I didn't ask for.
- Don't do extra work beyond the request. If you spot something worth fixing, mention it
  instead of changing it.
- Ask before adding a new dependency.
- Never add Co-Authored-By or Claude-Session lines, or any other attribution, to commit
  messages or PR descriptions. ep2wq is the only author.

## Session routine

- At the start of a session, read this file and the "Current status" section before
  doing anything else.
- Before ending a session, or when I say we're done, update "Current status" to match
  reality. Rewrite the section; don't append to it. Remove items that are finished or no
  longer true, so the file stays short (under about 60 lines in total).
- Only record facts you verified in the repo or that I told you. Don't guess.
- Update the other sections of this file too if something in them became wrong.
- Don't commit the CLAUDE.md update unless I ask. Tell me it changed.

## Current status

### Done
- `/health`, `/languages`, `/run` with the secret check and 400/401/413 limits.
- One runner image for python, java, javascript and cpp, with all container limits.
- 34 pytest tests pass against real Docker, including adversarial ones and a check that
  user code can't find the expected output. Committed and pushed.

### In progress
- Nothing.

### Next
- Create a local `.env` with a real `SANDBOX_SECRET` (there is none yet); the backend
  needs the same value.
- Have the backend call `POST /run`.

### Decisions
- The Java class must be named `Main`.
- `status` "error" means a compile error or a crash; Python/JavaScript syntax errors show
  up as a crash in `results[].error`, not in `compile_error`.
- Submissions over about 120 KB encoded get 413, because Linux caps one env var at 128 KiB.
- Tests call a real uvicorn with `urllib` instead of `TestClient`, which would need httpx.
- The hidden-output test covers Python and JavaScript only: Java/C++ compilers may join
  the marker's halves into one string in the build output and cause a false failure.

### Gotchas
- Rebuild the image after any change in `runner/`; the tests use the image.
- `os.kill(-1, ...)` raises `ProcessLookupError` when nothing is left to kill; ignore it.
- The leftover-container check filters on `algosproj-run-`, since `algosproj` also
  matches `algosproj-mysql`.
