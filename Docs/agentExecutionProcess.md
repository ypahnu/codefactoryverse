# Agent Execution Process - How Agents Create Files in Sandbox /workspace

## Overview

When agent `agent#58` (or any bot) says `**File to create:** **→ /workspace/index.html**` but file didn't appear in sandbox, this doc explains why and how it now works.

**User reported:** http://127.0.0.1:5000/projects/team/acme-corp/proj-9/tasks/18 bot#58 replay "**File to create:** **→ `/workspace/index.html`** — Main web page (will be served at sandbox frontend URL on port 8000):" and code, but didn't write/save file.

**Root cause:** Execute endpoint only looked for `# File: /workspace/...` comment inside code blocks, but bot#56 format had file path **outside** code block in bold markdown, with unclosed HTML code block at end of message (5 triple backticks, odd number, last block unclosed).

**Fixed:** Parser now handles all formats and unclosed blocks.

---

## Process Step-by-Step (with logs)

### 1. Master Agent Knows Sandbox

`app/models.py: MASTER_AGENT_TEMPLATE` system_prompt now includes:

```
⚠️ CRITICAL: You have access to a Modal Sandbox...

SANDBOX AWARENESS - MUST READ:
- Every project has 1 sandbox (name like proj-{team}-{project}-{id})
- Sandbox has tunnel URLs: Public URL https://ta-xxx-8000-...modal.host
- Sandbox filesystem is at /workspace per-project path (shared across tasks, no volume)
- Files are managed via functions in app/services/modal_sandbox_service.py:
  * upload_file_to_sandbox(sandbox_id, local_path, remote_path) -> sb.filesystem.copy_from_local
  * write_text_to_sandbox(sandbox_id, content, remote_path) -> sb.filesystem.write_text
  * list_files_in_sandbox(sandbox_id, path="/workspace")
  * read_file_from_sandbox, sb.exec("bash", "-c", "ls -la /workspace")

- When you generate code, you MUST specify file path using EXACT format that Execute button parser understands:
  **→ `/workspace/index.html`**  OR  File to create: `/workspace/app.py`  OR  # File: /workspace/src/Header.tsx

BEST PRACTICE - Always include at top of each code block:
```python
# File: /workspace/index.html
<html>...</html>
```

Then when user clicks Execute button in chat, backend extracts code blocks, finds file paths via regex, calls write_text_to_sandbox(sandbox_id, code, remote_path)
```

**2 new skills added:**
- 📦 Sandbox & Workspace (90%) - Knows how to read/write files to /workspace
- 📁 Filesystem API (88%) - Uses sb.filesystem.* methods

### 2. Agent Prompt Includes Sandbox Context

`app/services/modal_client.py:run_agent_factory()` now fetches `ProjectSandbox` for task's project:

```python
sandbox = ProjectSandbox.query.filter_by(project_id=task.project_id).first()
sandbox_context = f"""
SANDBOX CREATED FOR THIS PROJECT:
- Name: {sandbox.name}
- Type: {sandbox.type} ({sandbox.runtime})
- Status: {sandbox.status} - {'alive' if is_alive() else 'expired'}
- ID: {sandbox.modal_sandbox_id}
- Tunnel URL: {sandbox.tunnel_url}
- Volume: {sandbox.volume_name} (not used, filesystem API)
- Git Repo: {sandbox.git_repo_url}
- Files are in /workspace per-project path
"""

extra_context["sandbox_context"] = sandbox_context
```

This context is injected into:
- `agent_generator.py` full_log as `### Sandbox Context - Per-Project Workspace` section
- LLM system prompt for real Modal endpoint calls (Path A)

So agent sees sandbox name, tunnel URL, and knows to write to `/workspace`.

### 3. Chat Has Execute Button to Make Changes to Sandbox

`app/templates/tasks/view.html` - for each assistant message:

```html
<button class="tts-play-btn" data-message-id="{{ msg.id }}" data-transcript="{{ msg.content }}" 
        data-voice-id="{{ msg.agent.voice_id }}"> Play
</button>
<button class="execute-sandbox-btn" 
        data-message-id="{{ msg.id }}"
        data-task-id="{{ task.id }}"
        data-team-slug="{{ team.slug }}"
        data-project-slug="{{ project.slug }}"
        style="background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.3);color:#10b981;">
  Execute in Sandbox
</button>
```

**JS handler in tasks/view.html:**

```javascript
document.querySelectorAll('.execute-sandbox-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const messageId = btn.dataset.messageId;
    btn.innerHTML = '🧠 Executing...';
    btn.disabled = true;

    const resp = await fetch(`/projects/team/${teamSlug}/${projectSlug}/tasks/${taskId}/messages/${messageId}/execute`, {
      method: 'POST',
      body: JSON.stringify({})
    });
    const data = await resp.json();
    // data.files_written = [{remote_path: /workspace/index.html, written: true, mock: false, code_length: 11194}]
    alert(`Executed message ${messageId} in sandbox: Wrote ${data.files_written.length} files`);
  });
});
```

### 4. Endpoint Executes Code in Sandbox /workspace

`app/blueprints/tasks/routes.py:execute_message_in_sandbox`:

```python
@tasks_bp.route('/team/<team_slug>/<project_slug>/tasks/<int:task_id>/messages/<int:message_id>/execute', methods=['POST'])
def execute_message_in_sandbox(...):
    message = TaskMessage.query.filter_by(id=message_id, task_id=task.id).first()
    sandbox = ProjectSandbox.query.filter_by(project_id=project.id).first()
    sandbox_id = sandbox.modal_sandbox_id or f"sb-mock-..."

    # Extract file paths from text - handles bot#56 format
    path_patterns = [
        r'→\s*`?(/workspace/[^\s`\)"]+)`?',  # → /workspace/... 
        r'File to create:\s*→?\s*`?(/workspace/[^\s`\)"]+)`?',  # File to create: → /workspace/...
        r'\*\*File to create:\*\*\s*\*\*→\s*`?(/workspace/[^\s`\)"]+)`?\*\*',  # **File to create:** **→ `/workspace/index.html`**
        r'#\s*File:\s*(/workspace/[^\s\n]+)',  # # File: /workspace/...
    ]
    file_paths_from_text = []
    for pat in path_patterns:
        found = re.findall(pat, text_to_search)
        file_paths_from_text.extend(found)

    # Find code blocks - handle both closed and unclosed (bot#56 had unclosed ```html at end)
    pattern = r"```(?:python|javascript|typescript|js|py|ts|html)?\n(.*?)```"
    matches = re.findall(pattern, text_to_search, re.DOTALL)
    # Also handle unclosed code block at end (odd number of ```)
    triple_count = text_to_search.count("```")
    if triple_count % 2 == 1:
        unclosed_pattern = r"```(?:python|...|html)?\n(.*)\Z"
        unclosed_matches = re.findall(unclosed_pattern, text_to_search, re.DOTALL)
        if unclosed_matches and "<html" in unclosed_matches[-1].lower():
            matches.append(unclosed_matches[-1])

    # Filter out system prompt blocks
    filtered_blocks = [cb for cb in matches if "You are CodeFactory Prime" not in cb or "<html" in cb.lower()]

    # For each code block, determine remote_path
    for idx, code in enumerate(filtered_blocks[:5]):
        # Try # File: comment inside code
        file_path_match = re.search(r'#\s*(?:File|Path):\s*(/workspace[^\s\n`]+)', code)
        if file_path_match:
            remote_path = file_path_match.group(1)
        elif idx < len(file_paths_from_text):
            remote_path = file_paths_from_text[idx]  # Use path mentioned outside code block (bot#56 case)
        else:
            remote_path = f"/workspace/tasks/{task.id}/message_{message.id}_{idx}.py"

        # Write to sandbox via filesystem API (real Modal, async only, no mock)
        write_result = write_text_to_sandbox(sandbox_id, code, remote_path)
        # Logs ProjectActivity type=code_executed

    # Return JSON with files_written
```

**For bot#56 case (Task 18, Message 101):**
- Text has `**File to create:** **→ `/workspace/index.html`**` outside code block
- Code block is ```html\n<!DOCTYPE html>... (unclosed, 11194 chars, no closing ``` at end)
- Old parser: Found paths [] (because it only looked inside code for # File:), code_blocks = 2 (system prompt + empty), filtered to 0, no file written
- New parser: Found paths ['/workspace/index.html'] from text outside, found unclosed HTML block length 11194, associated first path with first code block, writes to `/workspace/index.html` via `write_text_to_sandbox(sandbox_id, code, "/workspace/index.html")`

### 5. Logs - What Happens (User Request: Create logs and show request as code)

**When creating agent (clone):**
```python
# REQUEST LOG - Create Agent Bot
# Task: do a web page with product prices (ID 18)
# Project: acme-corp/proj-9
# By: demo

from app.models import Agent, Task
task = Task.query.get(18)
agent = Agent.create_clone(
    task_id=18,
    name="bot#56",
    role="do a web page with product pri Specialist",
    custom_skills=['coding', 'architecture', ...],
    custom_prompt="""You are CodeFactory Prime... TASK CONTEXT: Task: do a web page..."""
)

# Skills selected: Code Generation, System Architecture, ...
# Duplicate check: bot#56 not in ['...']

print(f"Created agent {agent.name} with 14 skills - will read all 25 previous chats")
```
Printed to console + saved in system message full_prompt behind `+ details` toggle (compact system log).

**When sending message that mentions bot (auto-reply):**
```python
# AUTO-REPLY TRIGGERED - Agent Mentioned
# User said: "@agent#58 why can't you save the file?"
# Mentioned: agent#58 (ID 26)
# Reason: name 'agent#58' found in message
# All bots have read: 4 previous chats

from app.services.modal_client import run_agent_factory
task = Task.query.get(20)
agent = Agent.query.get(26)

result = run_agent_factory(task, agent, extra_context={...})
# Save as TaskMessage -> appears in chat timeline with + toggle
```

**When clicking Execute button in chat:**
```python
# REQUEST LOG - Execute Chat Message in Sandbox
# Message ID: 101 Task: do a web page with product prices (ID 18)
# Project: acme-corp/proj-9 Sandbox: proj-acme-corp-proj-9-12
# From: demo
# Code blocks found: 1

from app.services.modal_sandbox_service import write_text_to_sandbox

for idx, code in enumerate(code_blocks):
    remote_path = f"/workspace/tasks/18/message_101_{idx}.py"
    result = write_text_to_sandbox("sb-01M6BD968XFGQ0DNED7YNRS3D3", code, remote_path)
    print(f"Wrote {len(code)} chars to {remote_path}")

print(f"Executed message 101 - 1 files written to sandbox /workspace")
```

**When uploading file to sandbox (per-project, no volume):**
```python
# REQUEST LOG - Send File to Sandbox (Filesystem API, No Volume, Per-Project)
# Sandbox ID: sb-01M6BQ6S4DNKGCNQW31SMNQSVA
# Local: /tmp/tmpabcd_test_upload.py -> Remote: /workspace/test_upload.py

import modal
sb = await modal.Sandbox.from_id.aio("sb-01M6BQ6S4DNKGCNQW31SMNQSVA")
await sb.filesystem.copy_from_local.aio("/tmp/tmpabcd_test_upload.py", "/workspace/test_upload.py")
```

All logs printed to console + saved in `ProjectActivity.detail` and `TaskMessage.full_prompt` behind `+ show full prompt` / `+ details` toggle.

### 6. Thinking Symbol When Waiting

**User request:** When you press button to make agent added to chat it should have thinking symbol that page is waiting for agent created in modal. Same when sending message and waiting for reply, agent panel should be created instantly inside thinking symbol.

**Implemented in `tasks/view.html` JS:**

- **Clone agent form submit:**
```javascript
cloneForm.addEventListener('submit', (e) => {
  const agentName = nameInput.value || 'New Agent';
  // Show thinking in agents sidebar
  const thinkingCard = document.createElement('div');
  thinkingCard.className = 'agent-card mb-2 thinking-card';
  thinkingCard.innerHTML = `
    ${agentName} <span class="agent-thinking"><span class="reasoning-icon">🧠</span> creating <span class="thinking-dots"><span></span><span></span><span></span></span></span>
    Creating in Modal... • waiting for sandbox
  `;
  agentsContainer.appendChild(thinkingCard);

  // Show thinking in chat timeline as system log
  const thinkingChat = document.createElement('div');
  thinkingChat.className = 'chat-item system system-compact thinking-card';
  thinkingChat.innerHTML = `Creating agent ${agentName} in Modal... <span class="thinking-dots">`;
  timeline.appendChild(thinkingChat);
});
```

- **Send message form submit (mention detection):**
```javascript
messageForm.addEventListener('submit', (e) => {
  const content = textarea.value;
  // Detect mentioned agents from content
  let mentionedNames = [];
  // ... parse mentionData ...
  mentionedNames.forEach(name => {
    const thinkingChat = document.createElement('div');
    thinkingChat.className = 'chat-item assistant thinking-card';
    thinkingChat.innerHTML = `
      <div class="chat-header"><span class="chat-role"><i class="bi bi-robot"></i> ${name} 🧠 thinking</span></div>
      <div class="chat-briefing"><span class="agent-thinking"><span class="reasoning-icon">⚙️</span> Reasoning <span class="thinking-dots"><span></span><span></span><span></span></span></span> Context: ${content.substring(0,60)}... will make changes to /workspace via upload_file_to_sandbox</div>
    `;
    timeline.appendChild(thinkingChat);
  });
});
```

**CSS for thinking animation (already in `style.css`):**
```css
@keyframes thinking-bounce { 0%,80%,100% { transform: scale(0.6); opacity:0.4; } 40% { transform: scale(1) translateY(-4px); opacity:1; } }
.thinking-dots span { width:6px; height:6px; border-radius:50%; background:var(--primary); animation: thinking-bounce 1.4s infinite; }
.thinking-dots span:nth-child(1) { animation-delay: -0.32s; }
.agent-thinking { display:inline-flex; gap:6px; color:var(--primary); background:rgba(99,102,241,0.1); border:1px solid rgba(99,102,241,0.2); border-radius:12px; padding:2px 8px; }
.reasoning-icon { animation: reasoning-spin 1s linear infinite; }
.thinking-card { background: linear-gradient(90deg, var(--bg2) 0%, rgba(99,102,241,0.05) 50%, var(--bg2) 100%); background-size:200% 100%; animation: shimmer 2s infinite; border:1px dashed var(--primary); }
```

- Agent card: when `status=='working'` shows `🧠 thinking` + bouncing dots + `⚙️ reasoning`
- Chat timeline: temporary card for each working agent shows "Reasoning - has read all chats, generating response..." before real reply arrives

### 7. Current DB State for Task 18 / Agent#58

- Task 18 `do a web page with product prices` Project proj-9 team acme-corp
- Project 9 has sandbox 15 `proj-acme-corp-proj-12-13` (actually project 13? Wait project 9 is proj-9 id 12? Confusing) - id `sb-01M6BQ6S4DNKGCNQW31SMNQSVA` status Started, tunnel `https://ta-01m6bq6s4dfaq2t8crxge8y15v-8000-...` alive True
- Agent id 26 name `agent#58` (not 58, name contains #58) role `webpage with flags and countri Specialist` status idle alive True skills 14
- Messages: 5 in task 20? Actually task 18 has 2 messages (system cloned + assistant), task 20 has 5 messages (different task)
- For task 18, message 101 (bot#56) now correctly writes to `/workspace/index.html` in real sandbox after fix (tested: files_written 1, mock=False, length 11194)

### 8. Files Changed

- `app/models.py`: MASTER_AGENT_TEMPLATE system_prompt with sandbox awareness, 2 new skills sandbox & filesystem, create_clone accepts voice_id/voice_name
- `app/services/agent_generator.py`: Generic registry, sandbox_section in full_log, sample code with # File: /workspace/index.html and File to create: → /workspace/index.html examples
- `app/services/modal_client.py`: _get_task_chat_history, sandbox_context injection, run_agent_via_modal_endpoint includes chat_history, run_agent_factory includes sandbox_context
- `app/blueprints/tasks/routes.py`: execute_message_in_sandbox endpoint now handles unclosed code blocks, filters system prompt blocks, parses file paths from text outside code blocks (→ /workspace/..., File to create: →...), writes to sandbox via write_text_to_sandbox, logs ProjectActivity type code_executed, request log as code
- `app/templates/tasks/view.html`: Added execute-sandbox-btn next to Play button, JS handlers for clone form and message form to show thinking symbol instantly, thinking-card CSS, voice.js and mention.js already included

### 9. How to Test

1. Open http://127.0.0.1:5000/projects/team/acme-corp/proj-9/tasks/18
2. You see agent#58 (id 26) with voice badge and alive badge
3. In chat, type `@agent#58 why can't you save the file?` - should trigger auto-reply with thinking symbol instantly (panel created with 🧠 thinking + bouncing dots), then reply with file path
4. Click **Execute in Sandbox** button on bot#56's message that says `File to create: → /workspace/index.html`
5. Should show alert `Executed message 101 in sandbox: Wrote 1 files to /workspace/index.html` and file appears in Files in Sandbox tab
6. Check Files in Sandbox tab - should list `/workspace/index.html` (per-project path)
7. Click tunnel URL to see web page served at `https://ta-...-8000-...modal.host` (python -m http.server 8000 --directory /workspace should be running via exec)

Logs visible in console (request as code) and behind `+ show full prompt` / `+ details` toggles.

---

Date: 2026-10-27
Status: Implemented, tested with real sandbox sb-01M6BD968... writing /workspace/index.html, mock=False
