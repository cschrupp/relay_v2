# 0002 — Drive OpenCode through its session API, not the v2 API

**Date:** 2 November 2026
**Status:** Accepted

## Context

OpenCode 1.18 serves two HTTP APIs. The v2 API (`/api/session`, `/api/event`) has a
durable, replayable event stream, and Relay's adapter first used it. Its session
runner, however, only sees providers in the v2 model registry (`GET /api/model`). On
the developer's machine that registry held OpenCode Zen and one local model. Providers
signed in through `opencode auth` (OpenRouter, NVIDIA) appear only in the registry
behind the older session API (`GET /config/providers`). So `opencode run --model
openrouter/...` worked, while the v2 runner failed with "Model unavailable", or went
idle with nothing but a server log line.

## Decision

Relay drives OpenCode through the session API that `opencode run` uses:
`POST /session`, `GET /event` then `POST /session/{id}/prompt_async`,
`session.idle` to end a turn, `GET /session/status`, `POST /session/{id}/abort`, and
`GET /session/{id}` for tokens and reported cost. Relay does not register providers
with the v2 API: provider setup belongs to the developer.

## Consequences

- Every model the developer can use with `opencode run` works with `relay run`.
- This is an architectural dependency on an API OpenCode may deprecate. If it is
  removed or changes shape, `relay.runtime.opencode` is where Relay breaks. The
  adapter is the only module that knows the endpoints.
- The session API's event stream has no replay. A dropped stream is reconnected,
  and `GET /session/status` decides whether the turn is still running; events in the
  gap are not seen (they only feed the turn summary).
- Revisit when the v2 runner sees the same providers as `opencode run`.
