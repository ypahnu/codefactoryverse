# Modal App Removal - Why `modal_app.py` Was Deleted

## What Was Removed

File: `codefactoryverse/modal_app.py` (123 lines, standalone deployable)

It defined:
```python
app = modal.App("codefactory-agent-factory")

@app.function(image=image, secrets=[...])
@modal.fastapi_endpoint(method="POST")
def createAgent(payload: dict):
    # received task + agent config, returned briefing + full_log
```

Deployment: `modal deploy modal_app.py` → URL like `https://ac-xxx--codefactory-agent-factory-createagent.modal.run`

Flask would then POST to that URL via `MODAL_AGENT_URL` env.

## Why Removed (Decision: Path A)

User decided **Path A**: everything in `codefactoryverse`, no separate Modal App.

**Reasons:**
- Simpler - no extra deploy step, no Python 3.11/12 requirement (Modal SDK doesn't support 3.14, but Flask runs on 3.14)
- Current `.env` already uses Path A: `MODAL_ENDPOINT_HOST` set, `MODAL_AGENT_URL` empty, logs show `Source: modal-endpoint-direct`
- Less moving parts, easier to debug request logs as code in Flask
- `modal_app.py` was never imported anywhere (grep shows 0 imports), only HTTP call
- Path B added latency (Flask -> Modal web endpoint -> inference endpoint) vs Path A direct (Flask -> inference endpoint)

**What remains:**
- `app/services/modal_client.py` now only has `run_agent_via_modal_endpoint()` (Path A direct) + local mock fallback
- `app/config.py` no longer has `MODAL_AGENT_URL`, only `MODAL_ENDPOINT_HOST` + proxy tokens `wk-`/`ws-`
- `requirements.txt` still has `modal` package for endpoint listing, but not required for Path A (uses `openai` + `requests`)

## Impact

- ✅ Safe: No ModuleNotFoundError, no file imports `modal_app`
- ✅ Path A still works, local mock still works
- ❌ Path B disabled: setting `MODAL_AGENT_URL` now does nothing (removed from config)
- 📝 Docs updated: README, .env.example, Agents.md no longer reference Path B

## How to Restore If Needed

If you need decoupled scaling later, recreate `modal_app.py` from git history:
```bash
git show HEAD~1:codefactoryverse/modal_app.py > codefactoryverse/modal_app.py
```

Or create new file with `@modal.fastapi_endpoint` that calls `run_agent_via_modal_endpoint()` internally.

## Current Architecture After Removal

```
Flask (CodeFactory)
  → modal_client.py:run_agent_factory()
    → if MODAL_ENDPOINT_HOST + proxy_auth set:
        OpenAI client -> https://inference.us-west.modal.direct/v1
        model = MODAL_ENDPOINT_HOST (e.g. my-qwen--...modal.run)
        header Modal-Routing-Affinity-Key: task-{id}
    → else local mock via agent_generator.py
  → TaskMessage saved -> broadcast_to_task_agents() -> all bots read
```

No separate Modal App, everything in codefactoryverse.

Date: 2026-10-27
Decision by: user - Path A
