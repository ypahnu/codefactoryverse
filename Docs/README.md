# Docs - CodeFactory

Index of all documentation, organized per project parts.

## Main
- **../codefactoryverse/README.md** - Short main README (Quick Start, Stack, Features Summary, links to detailed docs)

## Database & Schema
- **DATABASE_REPORT.md** - Human-readable markdown: summary counts, schema (columns, types, FKs, unique), data rows, JOANA_BOT section, broadcast verification
- **DATABASE_FULL.json** - Full JSON export with all rows (users, teams, team_members, projects, tasks, agents, task_messages, message_reads, project_sandbox, project_activity, task_participants)
- Current DB: users 2, teams 2, projects 3 (now with sandbox), tasks 8, agents 10, messages 39+, reads 70+

## Agents & Lifespan
- **Agents.md** - Lifespan tracking, Modal sandbox lifecycle (Created/Scheduled/Started/Ready/Finished), timeouts (default 5min up to 24h), idle_timeout, return codes, how to check availability (from_id, from_name, list with tags, poll), snapshots (filesystem 30d, directory, memory 7d), resources, request logging as code examples, thinking icon CSS, Joana alive example

## Chat & Mention
- **mention.md** - @ mention autocomplete spec (generic for any bot, not Joana-specific)
  - Data sources: inTask (agents already in task, will answer), inProject (agents in project but different tasks, will be cloned without reselecting skills + added), people (team members, will be added to task via task_participants M2M)
  - Frontend: position-relative wrapper, #mention-dropdown, #mention-data JSON, mention.js 200 lines (getAtQuery, filterCandidates, keyboard nav Arrow/Enter/Esc)
  - Backend: tasks/routes.py view() loads team_members + project_agents + mention_data, add_message() regex @([\w\- ]+), clones project agents keeping original skills, adds people to task_participants
  - Generic personality: BOT_PERSONALITIES dict data-driven, _get_bot_personality() lookup, no hardcoded is_joana
  - New table: task_participants (task_id, user_id, added_via mention/manual/auto, added_at, added_by)

## Voice
- **voice.md** - TTS & STT plan, checking /voice and /tts_cartesia
  - Existing: /voice Meta Muse realtime WSS 24kHz PCM 80ms frames, /tts_cartesia Cartesia Sonic POST 100 voices, /3DAgents hybrid VoiceManager auto mode (Web Speech interim + MediaRecorder + Transformers local Whisper + server Whisper)
  - Proposed architecture: mic → VoiceManager → /api/voice/transcribe (Meta/WebSpeech/Whisper) → TaskMessage(message_type=voice, audio_url, transcript_source) → broadcast + auto-reply mention → Cartesia TTS → <audio autoplay>
  - DB changes: TaskMessage add audio_url, transcript_source, voice_id, tts_status
  - New blueprint voice/routes.py: POST transcribe + POST tts
  - New service cartesia_tts.py + meta_stt.py
  - Frontend: mic button, speaker button per message, voice selector dropdown from voices.json
  - Env: MODEL_API_KEY (Meta STT), CARTESIA_API_KEY (TTS)

## Workspace / Sandbox
- **workspace.md** - Workspace/sandbox per project (Option B chosen: separate tables)
  - Current Project fields: id, name, slug, description, team_id, owner_id, status, created_at, updated_at, color (no sandbox yet)
  - New Model ProjectSandbox (1-1 with Project): name (proj-team-project-id, unique per project for Modal named sandbox), display_name, type (project, project-vm, dev), runtime (gvisor|vm), status (Created/Scheduled/Started/Ready/Finished/terminated), modal_sandbox_id (sb-...), modal_app_id, image (codefactory-runtime), volume_name (codefactory-vol-team-project), cpu, memory, timeout 3600, idle_timeout 600, returncode, tunnel_enabled, tunnel_port 3000, tunnel_url, tunnel_urls_json, tunnel_last_seen, git_repo_url (separate repo), git_branch main, dev_command (npm run dev), install_command, snapshot_image_id, env_vars_json, created_at, last_heartbeat, expires_at
  - New Model ProjectActivity: for cross-task visibility (server restarting from other task while chatting) - project_id FK, task_id FK nullable, agent_id FK, user_id FK, type (sandbox_restart, server_start, tunnel_open, chat_mention, etc.), summary briefing, detail full log behind +, created_at
  - UI: partial _sandbox_status.html (badge status green/yellow/red, name/type/runtime/volume/ID short/uptime/CPU/Memory, tunnel URL clickable copy/open, buttons Start/Stop/Restart/Snapshot/Logs), include in projects/view.html header + tasks/view.html sidebar above Task Details, plus _activity_feed.html timeline last 20 events
  - New blueprint sandbox_routes.py: POST start (Sandbox.create name=project.sandbox.name, tags, volumes, timeout), stop (from_id terminate), restart, GET status JSON polling, GET tunnels sb.tunnels()
  - Minimum viable for user request: sandbox_name, sandbox_type, tunnel_enabled/port/url, status, volume, git_repo_url, dev_command

## Modal Removal
- **modal-removal/README.md** - Why modal_app.py deleted (123 lines, standalone, no imports, Path A chosen)
- **modal-removal/possibilities.md** - Variations:
  - A: Direct inference (chosen) - Flask → OpenAI SDK → Modal Inference Endpoint, no extra deploy, Python 3.14 compatible
  - B: Decoupled web endpoint (removed) - Flask → HTTP POST → modal_app.py → Inference, needs Python 3.11/12 + MODAL_AGENT_URL
  - C: 2-sandbox fleet (future) - Project Sandbox + Agent Sandbox sharing Volume, for isolated python/node runtime
  - D: Hybrid SDK remote (Flask calls Function.from_name().remote())

## Architecture (To Be Split)
- **architecture.md** (to create) - Full Path A architecture diagram, flow: Flask → modal_client.py → Modal Inference Endpoint → TaskMessage → broadcast

## Env Vars

```
MODEL_API_KEY=LLM_... (Meta Muse STT + generic LLM)
CARTESIA_API_KEY=sk_car_... (TTS)
MODAL_KEY=wk-... MODAL_SECRETE=ws-... (proxy for inference, Bearer wk-...ws-...)
MODAL_ENDPOINT_HOST=my-endpoint.us-west.modal.direct (Path A direct, no modal_app.py)
MODAL_WORKSPACE_ID=ac-...
MODAL_TOKEN_ID=ak-... MODAL_TOKEN_SECRET=as-... (for deploy, not needed for Path A)
```

## How to Regenerate Reports

```bash
cd codefactoryverse
python3 << 'PY'
from app import create_app; app=create_app()
...
PY
```

## JOANA_BOT Note

Joana is example of generic bot personality via BOT_PERSONALITIES registry. Any bot can have custom briefings, emoji, traits - not hardcoded. Joana kept alive for testing per user request (24h lifespan).

Last updated: 2026-10-27
