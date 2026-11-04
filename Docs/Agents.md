# Agents - Lifespan, Availability & Modal Sandboxes

## Overview

CodeFactory agents have **low lifespan by design** - they are clones of CodeFactory Prime that work on a specific task and expire.

### Current Implementation (DB Records)

```
Agent model fields:
- id, name, role, system_prompt, skills_json, task_id FK, status, model
- created_at, last_active_at, lifespan_seconds (default 3600 = 1h), expires_at, heartbeat_at
- modal_sandbox_id (if using Modal sandbox), modal_status (Created/Scheduled/Started/Ready/Finished)
- cloned_from
```

**Lifespan logic (`app/models.py`):**
- `lifespan_seconds = 0` => infinite (never expires)
- Default `3600` = 1 hour low lifespan for normal bots
- `JOANA_BOT` gets `86400` = 24h for testing per user request
- `is_alive()` checks `status != expired/failed` and `now < expires_at` (or `created_at + lifespan`)
- `time_to_expiry()` returns seconds remaining (negative if expired)
- `update_heartbeat()` extends expiry on each run: `expires_at = now + lifespan`

**Example from current DB:**
```
Agent 1 Auth Specialist #1: alive=False, expires_in=-16134s (expired 4.5h ago), lifespan 3600s
Agent 11 JOANA_BOT: alive=True, expires_in=86399s (23h left), lifespan 86400s
Agent 14 RIO: alive=True, expires_in=2411s (40min left)
```

Expired bots show in UI:
- Badge `<span class="badge bg-danger">expired</span>`
- Warning box: "This bot expired (low lifespan 3600s). Run it to extend lifespan (heartbeat) or clone new one."
- Alive badge: `<span class="badge bg-success"><i class="bi-heart-pulse"></i> alive</span>` + hourglass with seconds left

**How to check if agent still available:**
```python
agent.is_alive()  # True if not expired and status not failed/expired
agent.is_expired()  # inverse
agent.time_to_expiry()  # e.g. 2411 = 40min left, -16134 = expired 4.5h ago
agent.last_active_at  # last heartbeat
agent.heartbeat_at  # last Modal sandbox contact if used
```

**Extend lifespan:** Run agent (`POST /.../agents/{id}/run`) triggers `update_heartbeat()` which sets `expires_at = now + lifespan_seconds`. So active bots live longer.

---

## Modal.com Sandboxes - Low Lifespan Reality

If agents were to run inside Modal Sandboxes (instead of just DB records + local mock), their lifespan would be even lower per Modal docs:

### Lifecycle Events (from https://modal.com/docs/guide/sandboxes)

1. **Created** - Sandbox object exists, ID assigned, no compute yet
2. **Scheduled** - Assigned to worker, provisioning CPU/memory/volumes
3. **Started** - Container launched, entrypoint running, `exec()` now works, tunnels active
4. **Ready** - If readiness probe configured, probe succeeded, service ready for traffic (if no probe, this event skipped)
5. **Finished** - Stopped: entrypoint exited, explicit `terminate()`, timeout/idle timeout reached, or OOM. No further `exec` possible. Check `returncode` or dashboard.

### Timeouts

- **Default max lifetime: 5 minutes**
- Can be extended to **up to 24 hours** via `timeout` param:
  ```python
  sb = modal.Sandbox.create(app=app, timeout=10*60)  # 10 minutes
  sb = modal.Sandbox.create(app=app, timeout=24*60*60)  # max 24h
  ```
- For >24h, use **Filesystem Snapshots** to save state and restore in new sandbox:
  ```python
  snapshot_store[session_id] = sb.snapshot_filesystem().object_id
  sb.terminate()
  # later restore
  image = modal.Image.from_id(snapshot_store[session_id])
  sb2 = modal.Sandbox.create(image=image, app=app)
  ```

### Idle Timeouts

Sandbox auto-terminated after inactivity period via `idle_timeout` param. Considered **active** if:
1. Has active command running via `sb.exec(...)`
2. Its stdin being written to via `sb.stdin.write()`
3. Has open TCP connection over Tunnel

```python
sb = modal.Sandbox.create(app=app, idle_timeout=10*60)  # kill after 10min idle
```

### Return Codes (how to know if still available)

Unix-style exit codes to diagnose:
- Process: `p.returncode` / `p.poll()`
- Sandbox: `sb.returncode` / `sb.poll()`

```python
p = sb.exec("sh", "-c", "exit 42")
p.wait()
print(p.returncode)  # 42

sb.terminate(wait=True)
print(sb.returncode)  # 137 = SIGKILL from terminate
```

If `poll()` returns not None, sandbox finished (not available). If returns None, still running.

### Checking Availability via API

**From Modal SDK:**
```python
# By ID
sb = modal.Sandbox.from_id(sandbox_id)
try:
    sb.exec("echo", "hello")  # if fails, not available
except modal.exception.NotFoundError:
    print("Sandbox expired / terminated")

# By name (only if running)
sb = modal.Sandbox.from_name("my-app", "my-name")  # raises if not running

# List with tags to find available sandboxes for a project
for sb in modal.Sandbox.list(app_id=app_id, tags={"project_id": str(project_id), "team": team_slug}):
    print(sb.object_id, sb.returncode)  # returncode None = still available
```

**From CodeFactory (our implementation):**
- We store `modal_sandbox_id` and `modal_status` in Agent model
- `heartbeat_at` updated when we successfully `exec`
- If Modal Sandbox times out, `modal_status = "Finished"`, `is_alive()` should return False
- UI shows "expired" badge

### Runtimes

- **gVisor** (default): strong isolation, Google container runtime
- **VM**: full Linux kernel, needed for Docker inside sandbox, FUSE, cgroups
  ```python
  sb = modal.Sandbox.create(app=app, runtime="vm")
  ```

GPU Sandboxes only supported with `runtime="gvisor"` and are subject to preemption.

### Resource Limits

Sandboxes billed at `max(request, actual)`, can burst beyond request when spare capacity.

```python
sb = modal.Sandbox.create(
    cpu=0.5,           # request 0.5 cores
    memory=512,        # request 512 MiB
    cpu=(0.5, 4.0),    # request 0.5, limit 4.0
    memory=(512, 2048),# request 512, limit 2048
    app=app
)
```

Set limits to prevent misbehaving LLM-generated code from consuming unbounded resources.

### Snapshots for Long-Lived Agents

To preserve agent state beyond 24h timeout:

- **Filesystem Snapshot**: copy of root filesystem at point in time, saved as Image, TTL 30 days default (configurable, or None for indefinite)
  ```python
  image = sb.snapshot_filesystem(ttl=7*24*3600)  # 7 days
  sb2 = modal.Sandbox.create(image=image, app=app)
  ```
- **Directory Snapshot**: specific dir, can be mounted into already-running sandbox
  ```python
  snapshot = sb.snapshot_directory("/project")
  sb2.mount_image("/project", snapshot)
  ```
- **Memory Snapshot** (experimental): full RAM + filesystem, TTL 7 days, can restore exact running state including processes
  ```python
  sb = modal.Sandbox.create(..., _experimental_enable_snapshot=True)
  snapshot = sb._experimental_snapshot()
  sb2 = modal.Sandbox._experimental_from_snapshot(snapshot)
  ```

### Named Sandboxes for Project Isolation

Ensure only one running sandbox per project (your idea):

```python
# Only one running sandbox with this name at a time
sb1 = modal.Sandbox.create(app=app, name=f"proj-{project_id}")
# Second call raises AlreadyExistsError
sb2 = modal.Sandbox.create(app=app, name=f"proj-{project_id}")  # error!
```

Fetch by name:
```python
sb = modal.Sandbox.from_name("my-app", f"proj-{project_id}")  # only if running
```

---

## Logging - Request as Code (User Request)

When you create or send text to an agent, we now log request as code + print to console.

### Create Agent Log (in `agents/routes.py:create()`)

```python
# REQUEST LOG - Create Agent Bot
# Task: Task 1 (ID 5)
# Project: core-factory/codefactory-api
# By: demo

from app.models import Agent, Task

task = Task.query.get(5)

# Clone master agent CodeFactory Prime with 1 skills
agent = Agent.create_clone(
    task_id=5,
    name="JOANA_BOT",
    role="Task 1 Specialist",
    custom_skills=['planning'],
    custom_prompt="""You are CodeFactory Prime... TASK CONTEXT: Task: Task 1..."""
)

# Skills selected: Planning
# Duplicate check: joana_bot not in ['peter', 'joana_bot']

print(f"Created agent {agent.name} with 1 skills - will read all 8 previous chats")
```

This log is printed to console AND saved in system message full_prompt behind `+ details` toggle (compact system log).

### Send Text / Run Agent Log (in `agents/routes.py:run_agent()`)

```python
# REQUEST LOG - Send Text to Agent (Run Agent)
# Agent: JOANA_BOT (ID 11) - Role: Task 1 Specialist
# Task: Task 1 (ID 5) - Project: core-factory/codefactory-api
# Triggered by: demo
# Time: thinking...

from app.models import Task, Agent
from app.services.modal_client import run_agent_factory

task = Task.query.get(5)  # Task 1
agent = Agent.query.get(11)  # JOANA_BOT

# Chat history that all bots have read (last 10):
"""
[19:08] demo (user): Hey bots, all of you should read this! New requirement: make it blue!
[18:45] demo (user): joana can you imagine a web page for the task ?
[18:44] JOANA_BOT (assistant): Hiii!! I'm Joana...
"""

# Agent config:
agent_config = {
    "name": "JOANA_BOT",
    "role": "Task 1 Specialist",
    "skills": ['planning'],
    "model": "prime-v1",
    "system_prompt": """You are CodeFactory Prime..."""
}

print("🤔 Agent JOANA_BOT is thinking... [animated]")
result = run_agent_factory(task, agent, extra_context={...})
print(f"✅ JOANA_BOT replied: Blue sky thinking for Task 1!...")
print(f"📖 Broadcasted to 1 other bots - all have read it")
```

Saved in full prompt as:

```
# REQUEST AS CODE (what happened)
```python
...request log...
```

# RESPONSE FROM AGENT
Source: local-mock-with-history | Model: prime-v1

...full log with code, plan...
```

### Chat Auto-Reply on Mention (Joana)

When user posts message containing bot name (e.g., "joana can you imagine..."):

```python
# AUTO-REPLY TRIGGERED - Agent Mentioned
# User said: "joana can you imagine a web page for the task ?"
# Mentioned: JOANA_BOT (ID 11)
# Reason: name 'joana_bot' found in message

task = Task.query.get(5)
agent = Agent.query.get(11)

# Context: full chat history of 8 messages, all bots have read
chat_history = """[19:08] demo: Hey bots..."""

result = run_agent_factory(task, agent, extra_context={
    "triggered_by_mention": True,
    "mention_content": "joana can you imagine...",
    "chat_history": chat_history
})

# Save as TaskMessage -> appears in timeline with + toggle
```

Auto-reply limited to max 2 bots per user message to avoid spam, only triggers on user messages (not agent->agent to avoid loops).

---

## Thinking Animated Icon

Added CSS animations for reasoning state:

- `.thinking-dots` - 3 bouncing dots with staggered delay
- `.reasoning-icon` - spinning 🧠 / ⚙️ emoji
- `.agent-thinking` - pill badge with "thinking" + dots
- `.thinking-card` - shimmer background + dashed border when agent status=working

In `tasks/view.html`:
- Agent card: when `status=='working'` shows `🧠 thinking` + bouncing dots + `⚙️ reasoning`
- Chat timeline: temporary card for each working agent shows "Reasoning - has read all chats, generating response..."

---

## Current DB Example

```
Task 5 'Task 1' has 2 bots, 8 messages, 16 reads (8 per bot)
- JOANA_BOT: alive=True, expires_in=86399s (24h), read 8/8, status idle
- peter: alive=False (expired 1h lifespan), would need heartbeat to extend
```

To keep Joana alive for testing: `lifespan_seconds=86400`, `expires_at = now + 24h`.

To revive expired bot: Run it (POST run) → `update_heartbeat()` extends `expires_at = now + lifespan`.

---

## References

- Modal Sandboxes: https://modal.com/docs/guide/sandboxes (lifecycle, timeouts, idle, return codes, runtimes)
- Snapshots: https://modal.com/docs/guide/sandbox-snapshots (filesystem, directory, memory, TTL, forking)
- Resources: https://modal.com/docs/guide/sandbox-resources (CPU/memory request vs actual, bursting, limits, GPU)
- Endpoints: https://modal.com/docs/guide/endpoints (LLM inference hosting, proxy tokens wk-/ws-, affinity routing)
- Web Endpoints: https://modal.com/docs/guide/web-endpoints (fastapi_endpoint for createAgent)
