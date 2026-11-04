# Workspace / Sandbox per Project - Configuration & Visibility

## Overview

User request: project configurations should have sandbox name, type and tunnel. Example scenario: chatting in task and server will be restarting from other task, should be visible. Info should be available every page inside project.

Current Project model has no sandbox fields:
```python
id, name, slug, description, team_id FK, owner_id FK, status, created_at, updated_at, color
```

Need Option B (separate table) per user choice.

## Option B: Separate Tables (Chosen)

### New Model: ProjectSandbox (1-1 with Project)

```python
class ProjectSandbox(db.Model):
    id = db.Column(Integer, primary_key=True)
    project_id = db.Column(Integer, FK project.id, unique=True, index=True)  # 1-1
    name = db.Column(String(120), index=True)  # e.g. f"proj-{team.slug}-{project.slug}-{project.id}" -> "proj-core-factory-codefactory-api-1"
    display_name = db.Column(String(120), nullable=True)  # user-friendly
    type = db.Column(String(30), default='project')  # project, project-vm, dev, agent-factory
    runtime = db.Column(String(20), default='gvisor')  # gvisor | vm
    status = db.Column(String(30), default='unknown')  # Created, Scheduled, Started, Ready, Finished, terminated, unknown, error
    modal_sandbox_id = db.Column(String(100), nullable=True, index=True)  # sb.object_id
    modal_app_id = db.Column(String(100), nullable=True)
    image = db.Column(String(120), default='codefactory-runtime')
    volume_name = db.Column(String(120), nullable=True)  # codefactory-vol-{team}-{project}
    cpu = db.Column(Float, default=0.5)
    memory = db.Column(Integer, default=512)  # MiB
    timeout = db.Column(Integer, default=3600)  # seconds, max 24h per Modal
    idle_timeout = db.Column(Integer, default=600)  # seconds to auto-terminate if idle
    returncode = db.Column(Integer, nullable=True)  # exit code, 137 = SIGKILL
    # Tunnel
    tunnel_enabled = db.Column(Boolean, default=False)
    tunnel_port = db.Column(Integer, default=3000)
    tunnel_url = db.Column(String(512), nullable=True)  # from sb.tunnels()[port].url e.g. https://xxx-3000.modal.run
    tunnel_urls_json = db.Column(Text, nullable=True)  # JSON { "3000": "https://...", "8000": "..." }
    tunnel_last_seen = db.Column(DateTime, nullable=True)
    # Repo / dev server
    git_repo_url = db.Column(String(512), nullable=True)  # separate repo, not this Flask repo
    git_branch = db.Column(String(100), default='main')
    dev_command = db.Column(String(256), nullable=True)  # e.g. npm run dev, python -m flask run, python run.py
    install_command = db.Column(String(512), nullable=True)  # pip install -r requirements.txt
    # Snapshot for >24h persistence
    snapshot_image_id = db.Column(String(100), nullable=True)
    snapshot_created_at = db.Column(DateTime, nullable=True)
    # Env vars for sandbox
    env_vars_json = db.Column(Text, nullable=True)  # JSON dict {"PORT": "3000", "NODE_ENV": "dev"}
    # Timestamps
    created_at = db.Column(DateTime, default utcnow)
    last_heartbeat = db.Column(DateTime, nullable=True)
    expires_at = db.Column(DateTime, nullable=True)
    last_started_at = db.Column(DateTime, nullable=True)
    last_stopped_at = db.Column(DateTime, nullable=True)

    def is_alive(self):
        # Check status not Finished/terminated + heartbeat within idle_timeout + not expired
        pass

    def is_expired(self):
        return not is_alive()

    def time_to_expiry(self):
        # seconds until expires_at
        pass

    def tunnels(self):
        # Parse tunnel_urls_json -> dict
        return json.loads(self.tunnel_urls_json or "{}")

    def primary_tunnel_url(self):
        # Return tunnel_url or first from tunnel_urls_json
        pass
```

### New Model: ProjectActivity (Cross-Task Visibility)

Solves: "chatting in task and server will be restarting from other task. I should see it."

```python
class ProjectActivity(db.Model):
    id = db.Column(Integer, primary_key=True)
    project_id = db.Column(Integer, FK project.id, index=True)
    task_id = db.Column(Integer, FK task.id, nullable=True)  # which task triggered (optional)
    agent_id = db.Column(Integer, FK agent.id, nullable=True)
    user_id = db.Column(Integer, FK user.id, nullable=True)
    type = db.Column(String(50), index=True)  # sandbox_created, sandbox_started, sandbox_restart, sandbox_stopped, server_start, server_stop, tunnel_open, tunnel_closed, git_pull, deploy, chat_mention, agent_joined, task_created
    summary = db.Column(String(300))  # briefing visible by default: "Server restarting in task2 by JOANA_BOT"
    detail = db.Column(Text, nullable=True)  # full logs hidden behind + button (like TaskMessage)
    created_at = db.Column(DateTime, default utcnow)

    # Relationships
    project = relationship('Project', backref=backref('activities', lazy='dynamic', order_by='ProjectActivity.created_at.desc()'))
```

Query last 20 ordered desc, show as timeline in projects/view and as sidebar in tasks/view.

## Minimum Viable Fields for User Request

For "sandbox name, type and tunnel" visible every page:

1. **sandbox_name** - unique per project, e.g. `proj-core-factory-codefactory-api-1`, use as Modal Sandbox `name` param (ensures only one running per project, second create raises AlreadyExistsError)
2. **sandbox_type** - `project` vs `project-vm` (vm needed for Docker)
3. **sandbox_status** - Created/Scheduled/Started/Ready/Finished + `last_heartbeat`
4. **sandbox_id** - Modal object_id `sb-...` for recovery via `Sandbox.from_id()`
5. **tunnel_enabled**, **tunnel_port** (default 3000), **tunnel_url** (primary), **tunnel_urls_json** (multiple ports)
6. **sandbox_volume_name** - `codefactory-vol-{team}-{project}` for shared FS
7. **git_repo_url** + **dev_command** - what code is running
8. **created_at**, **expires_at** - uptime display

Nice-to-have: `snapshot_image_id`, `cpu`, `memory`, `runtime`, `app_id`, `returncode`, `env_vars_json`

## UI/UX Plan

### Project Config Page (New or Edit)

`templates/projects/edit.html` extended or new `templates/projects/sandbox.html`:

```
Header: Project Name + Save
Section: Workspace / Sandbox
  - [Checkbox] Sandbox Enabled (default True)
  - Display: Sandbox Name (auto-generated read-only, e.g. proj-core-factory-api-1) + Edit icon
  - Select: Sandbox Type (project, project-vm, dev) -> help text
  - Select: Runtime (gvisor, vm) -> gvisor strong isolation, vm for Docker
  - Input: Image (default codefactory-runtime) with help "prefer named images"
  - Input: Volume Name (auto codefactory-vol-{team}-{project})
  - Inputs: CPU (0.5) Memory (512 MiB) Timeout (3600s) Idle Timeout (600s)
  - Toggle: Tunnel Enabled + Port (3000) + URL display (read-only after start)
  - Input: Git Repo URL (separate repo, not Flask repo)
  - Input: Branch (main)
  - Input: Dev Command (npm run dev)
  - Input: Install Command (pip install -r requirements.txt)
  - Textarea: Env Vars JSON (optional)
  - Buttons: Save + Test Connection
```

### Sandbox Status Partial (Reusable)

New file `templates/projects/_sandbox_status.html`:

```
Card:
  Header: Workspace Status [Badge: Started green / Scheduled yellow / Finished red]
  Body:
    Row 1: Name: proj-... | Type: project | Runtime: gvisor | Volume: codefactory-vol-... | ID: sb-xxx (short)
    Row 2: Uptime: 1h 23m | CPU: 0.5 | Memory: 512 MiB | Created: Oct 27 21:00
    Row 3: Tunnel: https://xxx-3000.modal.run (3000) [Copy] [Open] + if multiple, list from tunnel_urls_json
    Row 4: Git: https://github.com/xxx/repo (branch main) | Dev: npm run dev
    Row 5: Buttons: Start / Stop / Restart / Snapshot / Logs / Open Tunnel
  Footer: Last heartbeat: 2 min ago | Expires in: 45 min | Returncode: None (running)
```

Include partial in:
- `projects/view.html` top header row next to stats (existing stats: total, done, in_progress, todo)
- `tasks/view.html` sidebar above "Task Details" as "Project Workspace" card - so while chatting in task, you see if server restarting from other task (via ProjectActivity last 5)
- Maybe also in `base.html` navbar dropdown "Workspace" if project context present?

### Activity Feed Partial

`templates/projects/_activity_feed.html`:

```
Card: Project Activity (last 20)
Timeline: vertical line with dots, each event:
  [ICON] [TYPE] summary (briefing) + time ago
  + show full prompt button for detail (like TaskMessage)
  Examples:
    🟢 Server started in task2 by JOANA_BOT - 2 min ago
    🔴 Server restarting from task1 by peter - 5 min ago
    🔵 Tunnel opened :3000 -> https://xxx.modal.run - 10 min ago
    💬 @JOANA_BOT mentioned in task2 - 15 min ago
    🤖 Agent rod cloned via @ mention - 20 min ago
```

Query: `ProjectActivity.query.filter_by(project_id=project.id).order_by(created_at.desc()).limit(20).all()`

Include in both `projects/view.html` and `tasks/view.html`.

### New Blueprint

`app/blueprints/projects/sandbox_routes.py`:

```python
sandbox_bp = Blueprint('sandbox', __name__)

@POST /team/<team>/project/<project>/sandbox/start
  -> Modal SDK: Sandbox.create(name=project.sandbox.name, image=Image.from_name(...), volumes={/workspace: Volume.from_name(...)}, timeout, idle_timeout, cpu, memory, runtime, tags={team, project, project_id})
  -> store sandbox_id, status=Started, last_heartbeat=now, expires_at=now+timeout
  -> create ProjectActivity type=sandbox_started, summary=f"Server started in task {task.title if task else 'project'} by {user}"

@POST /stop
  -> Sandbox.from_id(sandbox_id).terminate()
  -> update status=Finished, returncode, last_stopped_at

@POST /restart
  -> stop + start + ProjectActivity type=sandbox_restart

@GET /status (JSON)
  -> poll sandbox via from_id, update status, heartbeat, returncode, tunnels

@GET /tunnels
  -> sb.tunnels() -> dict port->url -> update tunnel_url, tunnel_urls_json, tunnel_last_seen

@POST /snapshot
  -> sb.snapshot_filesystem() -> snapshot_image_id, snapshot_created_at
```

### Config Additions

`app/config.py`:

```python
MODAL_SANDBOX_IMAGE = env MODAL_SANDBOX_IMAGE default codefactory-runtime
MODAL_SANDBOX_RUNTIME = env MODAL_SANDBOX_RUNTIME default gvisor
MODAL_SANDBOX_TIMEOUT = int(env MODAL_SANDBOX_TIMEOUT default 3600)
MODAL_SANDBOX_IDLE_TIMEOUT = int(env MODAL_SANDBOX_IDLE_TIMEOUT default 600)
MODAL_SANDBOX_CPU = float(env SANDBOX_CPU default 0.5)
MODAL_SANDBOX_MEMORY = int(env SANDBOX_MEMORY default 512)
MODAL_VOLUME_PREFIX = env MODAL_VOLUME_PREFIX default codefactory-vol
```

## Example: How It Looks

**Project Config Page:**

```
Workspace / Sandbox
-------------------
[X] Sandbox Enabled

Sandbox Name: proj-core-factory-codefactory-api-1 (auto) [Edit]
Type: [project ▼] Runtime: [gvisor ▼]
Image: [codefactory-runtime]
Volume: [codefactory-vol-core-factory-codefactory-api] (auto)

Resources: CPU [0.5] Memory [512] MiB
Timeouts: Timeout [3600]s Idle [600]s

Tunnel: [X] Enabled Port [3000] URL: https://abc-3000.modal.run [Copy] [Open]
  Additional: {"3000": "https://...", "8000": "https://..."}

Git Repo: [https://github.com/user/repo] Branch [main]
Dev Command: [npm run dev] Install: [npm install]

Env JSON: {"PORT": "3000"}

[Save] [Test Connection]
```

**Project View + Task View (shared status):**

```
Top of projects/view.html:
[ Project: CodeFactory API • Color dot ]
[ Stats: 8 tasks 2 done etc ]
[ Workspace Status Card: Started green | proj-... | Tunnel https://...:3000 [Open] | Uptime 1h | Buttons Start/Stop/Restart ]

Sidebar in tasks/view.html:
[ Project Workspace Card (same as above, compact) ]
[ Activity Feed: last 5 events from ProjectActivity, e.g. "Server restarting from task2 by JOANA_BOT - 2 min ago" ]
[ Task Details Card ]
```

This way, when chatting in Task 1 and server restarts from Task 2, you see activity feed update in real-time (via polling or after refresh).

## DB Migration Plan

- Create new tables via `db.create_all()` (preserves existing data, no drop)
- For existing projects (2 currently), create default sandbox entries:
  - name = f"proj-{team.slug}-{project.slug}-{project.id}"
  - type = project, runtime = gvisor, status = unknown
  - volume_name = f"codefactory-vol-{team.slug}-{project.slug}"
  - timeout 3600, idle 600

## Files to Modify (When Build Mode)

- `app/models.py` - add ProjectSandbox + ProjectActivity models
- `app/blueprints/projects/routes.py` - handle new fields in create/edit
- `app/templates/projects/create.html`, `edit.html` - add inputs
- `app/templates/projects/view.html` - include _sandbox_status.html + _activity_feed.html
- `app/templates/tasks/view.html` - include same partials in sidebar
- `app/blueprints/projects/` - new `sandbox_routes.py` blueprint
- `app/services/modal_sandbox_service.py` - wrapper for Modal SDK Sandbox.create, from_id, from_name, list, tunnels, snapshot
- `app/config.py` - add sandbox defaults
- `app/__init__.py` - register sandbox blueprint
- New templates `templates/projects/_sandbox_status.html`, `_activity_feed.html`
- Docs: this file `Docs/workspace.md` is the spec

Date: 2026-10-27
Chosen: Option B separate table
Status: Spec ready, not yet implemented (plan mode)
