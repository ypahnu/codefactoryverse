# Architecture - CodeFactory Path A (Everything in codefactoryverse)

## Overview

Flask app with teams → projects → tasks (chat timeline) → cloneable agents. Path A chosen: everything in codefactoryverse, no separate Modal App (modal_app.py deleted).

## Stack

- Flask 3.0.3, Flask-SQLAlchemy, Flask-Login, Flask-Migrate, Flask-WTF
- SQLite (codefactory.db) - 10 tables after new features
- Bootstrap5 + Vanilla JS + custom CSS (dark factory theme)
- Modal.com for LLM inference (Path A direct via OpenAI SDK), not for sandbox hosting yet
- Voice future: Meta Muse STT + Cartesia TTS

## Flow: User Adds Chat Message with @ Mention

```
1. User types in #chat-content-input textarea in tasks/view.html
   - JS mention.js detects @ at cursor, shows dropdown #mention-dropdown
   - Filters inTask (agents already in task), inProject (agents in other tasks of same project), people (team members)
   - User selects @JOANA_BOT or types @jo and selects

2. POST /projects/team/{team}/project/{project}/tasks/{id}/message
   - Form: content="Hey @JOANA_BOT...", role=user, message_type=chat
   - Backend tasks/routes.py:add_message():
     a. Creates TaskMessage(content, role=user, task_id)
     b. Logs request as code (print to console + logger.info)
     c. Broadcast: msg.broadcast_to_task_agents() -> creates MessageRead for all agents in task
     d. Detect mentions:
        - inTask agents whose name in content -> auto-reply via run_agent_factory()
        - inProject agents not in current task whose name matches -> clone with same skills (not reselecting) via Agent.create_clone(task_id=current, custom_skills=original.get_skills())
        - People: team member username/display_name in content -> add to task_participants M2M + system message "👤 @username added to channel"

3. Auto-reply for mentioned agents:
   - Set agent.status='working' (triggers thinking icon 🧠 + bouncing dots)
   - Call modal_client.py:run_agent_factory(task, agent, extra_context={triggered_by_mention, mention_content, chat_history})
     - _get_task_chat_history() gets last 20 messages (all bots have read)
     - Tries Path A: if MODAL_ENDPOINT_HOST + proxy_auth set -> OpenAI client -> https://inference.us-west.modal.direct/v1 with model=endpoint_host + header Modal-Routing-Affinity-Key: task-{id} for KV-cache
     - Else fallback local mock via agent_generator.py:generate_agent_response() with personalized briefings from BOT_PERSONALITIES registry (generic, not just Joana)
   - Creates TaskMessage role=assistant, agent_id=mentioned_agent.id, content=briefing visible, full_prompt=full_log + request log as code hidden behind + toggle
   - Broadcast reply to all other bots, mark read by author, set status idle + update_heartbeat() extending expires_at

4. Frontend shows:
   - New user message with Read by X bots badges (eye icon)
   - System log compact for clones/adds: "Agent cloned: name • X skills • will read all chats" with SYS label small
   - Assistant replies with briefing visible, + show full prompt for full log including request as code
   - Agent cards show thinking icon when working, alive/expired badge, read count X/Y
```

## Data Model (Current)

- **user**: id, username, email, password_hash, display_name, avatar_url, bio, created_at, is_active
- **team**: id, name, slug unique, description, owner_id FK user, avatar_color, created_at, members M2M via team_members, projects
- **team_members**: team_id FK, user_id FK, role, joined_at
- **project**: id, name, slug, description, team_id FK, owner_id FK, status, created_at, updated_at, color, tasks, sandbox (1-1)
- **project_sandbox** (new Option B): id, project_id FK unique, name, display_name, type, runtime, status, modal_sandbox_id, modal_app_id, image, volume_name, cpu, memory, timeout, idle_timeout, returncode, tunnel_enabled, tunnel_port, tunnel_url, tunnel_urls_json, tunnel_last_seen, git_repo_url, git_branch, dev_command, install_command, snapshot_image_id, snapshot_created_at, env_vars_json, created_at, last_heartbeat, expires_at, last_started_at, last_stopped_at, is_alive(), tunnels()
- **project_activity** (new): id, project_id FK, task_id FK nullable, agent_id FK, user_id FK, type (sandbox_restart, server_start, tunnel_open, chat_mention, etc.), summary briefing, detail full log behind +, created_at - for cross-task visibility (server restarting from other task visible while chatting)
- **task**: id, title, description briefing, full_prompt hidden, status todo/in_progress/done/blocked, priority, project_id FK, creator_id FK, assignee_id FK, position, created_at, updated_at, due_date, agents, messages, participants M2M via task_participants
- **task_participants** (new): task_id FK, user_id FK, added_via mention/manual/auto, added_at, added_by FK user - persistent when @ mentioning people
- **agent**: id, name, role, system_prompt, skills_json, task_id FK, status idle/working/completed/failed/expired, model, created_at, last_active_at, lifespan_seconds 3600 default (low), expires_at, heartbeat_at, modal_sandbox_id, modal_status, cloned_from, get_skills(), is_alive(), is_expired(), time_to_expiry(), update_heartbeat()
- **task_message**: id, task_id FK, agent_id FK nullable, user_id FK nullable, role user/assistant/system/briefing, content visible, full_prompt hidden behind +, message_type chat/briefing/log/commit/test/voice, created_at, reads relationship, has_full_prompt(), get_read_agents(), broadcast_to_task_agents()
- **message_read**: id, message_id FK, agent_id FK, read_at, unique(message_id, agent_id) - tracks which bots read which chats, broadcast feature

## Services

- **agent_generator.py**: Generic bot personality registry BOT_PERSONALITIES dict (JOANA_BOT is one entry, not hardcoded is_joana checks), _get_bot_personality() lookup exact/upper/lower, generate_agent_response() with chat_history included, skill_lines, model_section, mcp/api sections, personality_section generic. generate_clone_message() compact.
- **modal_client.py**: Path A only now - _get_config() reads MODAL_ENDPOINT_HOST + proxy_auth, _get_task_chat_history() last 20, run_agent_via_modal_endpoint() OpenAI client to Modal inference, run_agent_local_mock() fallback with history, run_agent_factory() tries endpoint then mock.
- **cartesia_tts.py** (future): tts_bytes_request() from tts_cartesia/run.py
- **meta_stt.py** (future): transcribe_realtime() from voice/run.py WSS

## Blueprints

- **auth**: login, register, logout
- **dashboard**: overview with stats teams/projects/todo/done
- **teams**: index, create, view, invite, delete
- **projects**: create, view (kanban todo/in_progress/done), edit, delete
- **projects/sandbox_routes.py** (future): POST start/stop/restart, GET status/tunnels -> Modal SDK Sandbox.create/from_id, tunnels(), snapshot_filesystem()
- **tasks**: create, view (with mention_data for autocomplete), edit, delete, add_message (with mention detection + clone without reselecting skills + add people to participants + broadcast + auto-reply), sync-reads, status
- **agents**: create (with duplicate name check, allow 0 skills via skills_present hidden field, request logging as code), view, delete (orphan messages agent_id=NULL, delete reads), run (thinking icon, heartbeat, request log as code, broadcast)
- **voice** (future): transcribe, tts

## Frontend

- **base.html**: navbar, flash alerts, Bootstrap 5.3.3, icons, Inter + JetBrains Mono fonts, loads style.css + app.js + mention.js
- **tasks/view.html**: Main chat timeline with dots (briefing orange, assistant green, system gray, system-compact small for logs), chat-item with header role badge + time, briefing, read receipts eye icon + badges, + show full prompt toggle (hidden div), thinking indicators for working agents (bouncing dots + reasoning spin), add message form with @ mention dropdown, mention-data JSON, badges for counts (in task/in project/people), agents sidebar with clone button, master agent info, agent cards with thinking-card shimmer when working, skill badges, read count + alive/expired + hourglass, compact system logs
- **mention.js**: getAtQuery() finds @ before cursor, filterCandidates() case-insensitive, renderDropdown() with sections, keyboard nav Arrow/Enter/Esc, click select replace @query with @ExactName
- **app.js**: btn-expand toggle, status-changer fetch, skill-toggle count, textarea auto-resize
- **style.css**: dark theme vars, chat timeline vertical line, chat-item, chat-item.system-compact (padding 6px 10px, dashed border, 6px dot), thinking-dots bouncing, reasoning-icon spin, agent-thinking pill, thinking-card shimmer, mention-dropdown, kanban cols, task-card

## Voice Plan (Future)

- Mic button in tasks/view.html toolbar
- VoiceManager.js from 3DAgents: MediaRecorder 24kHz PCM or webm opus, Web Speech interim, fallback to Meta Muse realtime WSS (needs MODEL_API_KEY) or server Whisper
- POST /voice/transcribe -> TaskMessage(message_type=voice, audio_url, transcript_source)
- Per-message speaker button -> Cartesia TTS via cartesia_tts.py -> saves WAV to uploads/voice/{task_id}/{message_id}.wav
- Env: MODEL_API_KEY (Meta STT), CARTESIA_API_KEY (TTS)

## Workspace / Sandbox (Future)

- Project config has sandbox name (proj-team-project-id), type (project/project-vm/dev), runtime (gvisor/vm), status, volume_name, tunnel_enabled/port/url, git_repo_url, dev_command
- Partial _sandbox_status.html reusable in projects/view.html header + tasks/view.html sidebar
- Activity feed _activity_feed.html for cross-task visibility: "Server restarting from task2 by JOANA_BOT"
- Sandbox routes: start (create with name unique, tags, volumes, timeout), stop (terminate), restart, status (poll), tunnels (sb.tunnels()), snapshot (snapshot_filesystem)

## Env

```
MODEL_API_KEY=LLM_... (Meta Muse STT + generic LLM)
CARTESIA_API_KEY=sk_car_... (TTS)
MODAL_KEY=wk-... MODAL_SECRETE=ws-... (proxy for inference, Bearer wk-...ws-...)
MODAL_ENDPOINT_HOST=my-endpoint.us-west.modal.direct (Path A direct, no modal_app.py)
MODAL_WORKSPACE_ID=ac-... MODAL_TOKEN_ID=ak-... MODAL_TOKEN_SECRET=as-... (for deploy, not needed for Path A)
```

## No modal_app.py

Deleted per user decision Path A. Everything from codefactoryverse. See Docs/modal-removal/ for possibilities A/B/C/D.

Date: 2026-10-27
Path A chosen, everything in codefactoryverse
