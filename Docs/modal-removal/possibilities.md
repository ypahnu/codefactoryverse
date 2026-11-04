# Modal Integration Possibilities / Variations

After removing `modal_app.py`, here are all possible variations for Modal integration, with tradeoffs.

## Variation A: Direct Inference - Path A (CHOSEN, Current)

**Flow:** Flask → OpenAI SDK → Modal Inference Endpoint

```
Flask app (codefactoryverse)
  → modal_client.py:run_agent_via_modal_endpoint()
    → openai.OpenAI(base_url="https://inference.us-west.modal.direct/v1", api_key="wk-...ws-...")
    → client.chat.completions.create(model=MODAL_ENDPOINT_HOST, messages=[...], extra_headers={"Modal-Routing-Affinity-Key": task_id})
    → returns briefing + full_log
  → TaskMessage → broadcast
```

**Pros:**
- Everything in codefactoryverse, single repo
- No extra deploy step
- Works on Python 3.14 (Modal SDK not needed for inference call, only openai + requests)
- Simplest request logging as code
- KV-cache reuse via affinity key
- Uses existing proxy tokens wk-/ws-

**Cons:**
- No isolation for agent execution (runs in Flask process, not sandbox)
- No scaling separate from Flask
- Secrets (proxy token) in Flask env, not Modal secrets

**Env:**
```
MODAL_ENDPOINT_HOST=my-endpoint.us-west.modal.direct
MODAL_KEY=wk-...
MODAL_SECRETE=ws-...
```

**When to use:** MVP, Phase 0-1, local dev, keep DB as source of truth.

---

## Variation B: Decoupled Web Endpoint - Path B (REMOVED)

**Flow:** Flask → HTTP POST → Modal App (modal_app.py) → Inference Endpoint

```
Flask app
  → requests.post(MODAL_AGENT_URL, json=payload, headers=Bearer wk-...ws-...)
  → Modal App: codefactory-agent-factory (deployed via modal deploy modal_app.py)
    @app.function(image=agent_image)
    @modal.fastapi_endpoint(method="POST")
    def createAgent(payload):
        # optionally calls inference endpoint
        return {briefing, full_log}
  → Flask saves as TaskMessage
```

**Pros:**
- Scales independently (Modal autoscaling containers)
- Secrets in Modal (Secret.from_name), not Flask
- Can include opencode binary, heavy deps in agent_image without bloating Flask
- Python entrypoint for agent logic isolated

**Cons:**
- Extra deploy step, needs Python 3.11/12 (Modal SDK doesn't support 3.14)
- Extra latency (Flask -> Modal web -> inference)
- Needs MODAL_AGENT_URL env, token secret as-... for deploy (user's was empty)
- More moving parts, harder to debug local

**Env:**
```
MODAL_AGENT_URL=https://ac-xxx--codefactory-agent-factory-createagent.modal.run
MODAL_KEY, MODAL_SECRETE still needed if modal_app.py itself calls inference
MODAL_TOKEN_ID=ak-..., MODAL_TOKEN_SECRET=as-... for deploy
```

**Why removed:** User decided Path A, simpler.

**How to restore:** `git show HEAD~1:codefactoryverse/modal_app.py > codefactoryverse/modal_app.py` + re-add `MODAL_AGENT_URL` to config.

---

## Variation C: 2-Sandbox Fleet - Project + Agent Sandboxes Sharing Volume (Future)

**Ideas from backups/Important Work/codefactoryverse/modal_app.py prototype:**

```
Flask app
  → Project Sandbox Fleet (App: codefactory-projects)
    - 1 Sandbox per Project (singleton, named proj-{project.id})
    - Image: codefactory-runtime (python, node, git)
    - Volume: codefactory-vol-{team}-{project} @ /workspace
    - Long-lived timeout 1h, idle_timeout 10m, tags project_id, team
    - Contains git repo, dev server, Tunnel url

  → Agent Sandbox Fleet (App: codefactory-agent-factory)
    - Function createAgent spawns ephemeral agent Sandbox per agent run
    - Agent Sandbox mounts SAME project volume to do work
    - Ephemeral: dies after task, volume persists file changes
    - Returns logs -> TaskMessage

Volume is contract: both fleets share same Volume, so agent writes files that project sandbox sees.

Flow:
1. Project create -> create Volume + Project Sandbox (sb.object_id stored)
2. Task agent run -> spawn Agent Sandbox mounting same Volume at /workspace/tasks/{id}
3. Agent Sandbox exec python agent_runner.py, writes to volume, terminates, volume.commit()
```

**Pros:**
- Strong isolation: agent pip install doesn't break project
- Security: untrusted LLM code in throwaway sandbox
- Concurrency: 5 agents mount same volume simultaneously vs contending in 1 container
- Persistent files across tasks via Volume + Snapshots for >24h
- Dev server tunnel per project visible across tasks

**Cons:**
- Complex, needs Modal Volumes, Snapshots, Tunnels handling
- Cost: 2 fleets, volume storage
- Need to handle sandbox lifecycle (Created, Scheduled, Started, Ready, Finished), timeouts, idle_timeouts, returncode 137

**Env/DB fields needed (see Docs/workspace.md):**
- ProjectSandbox table: sandbox_name, type, runtime, status, modal_sandbox_id, volume_name, tunnel_url, git_repo_url, dev_command, etc.
- ProjectActivity table for cross-task visibility (server restarting from other task)

**When to use:** When project has own repo (not same as Flask repo), needs isolated python/node runtime, dev server preview.

---

## Variation D: Hybrid - Flask Calls Modal Function via SDK (Not HTTP)

**Flow:** Flask has Modal SDK installed + token, calls Function directly:

```python
from modal import Function
fn = Function.from_name("codefactory-agent-factory", "run_agent_job")
result = fn.remote(payload)  # or fn.spawn.remote for async
```

**Pros:**
- No HTTP URL needed, uses Modal's internal RPC
- Can use .spawn for async jobs, poll status
- Secrets managed in Modal

**Cons:**
- Needs MODAL_TOKEN_ID ak-... + MODAL_TOKEN_SECRET as-... in Flask env (secret missing currently)
- Needs Python 3.11/12 for Modal SDK (not 3.14)
- Still needs modal_app.py deployed

**When to use:** If you want async job queue and have valid token secret.

---

## Recommendation

- **Now:** Variation A (chosen) - everything in codefactoryverse, direct endpoint, local mock fallback. Simple, works on 3.14, no modal_app.py.
- **Later for real projects:** Variation C (2-sandbox fleet) with ProjectSandbox table (Option B) for workspace isolation + volume sharing + tunnels visible across pages.

Date: 2026-10-27
Decision: Path A
