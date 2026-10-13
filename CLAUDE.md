# CLAUDE.md

## Project overview

AlgosProj is an interactive learning platform for data structures and algorithms.
Students read a lesson, watch a visualization, write code in the browser (Python or
Java), and the code is run against test cases. Passing earns points on a leaderboard.
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

- Stack: Python, FastAPI, Docker SDK for Python.
- Each submission runs in its own container, destroyed afterward. Every container must
  have: no network, a hard timeout of a few seconds, a memory cap of about 128 to 256 MB,
  a non-root user, and a read-only filesystem apart from a scratch directory.
- Languages: Python first, Java second. Each language is a Docker image plus a small
  wrapper that runs the code against the test cases and prints JSON. The wrapper's output
  format must be the same for every language so a new language doesn't change the API.
- Reject any request that doesn't carry the shared secret in the `X-Sandbox-Secret` header.
- Commands: `python -m venv venv`, `pip install -r requirements.txt`,
  `uvicorn app.main:app --reload`.

## Working rules

- Keep code simple. Don't add abstractions, patterns or dependencies I didn't ask for.
- Don't do extra work beyond the request. If you spot something worth fixing, mention it
  instead of changing it.
- Ask before adding a new dependency.
