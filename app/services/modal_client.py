"""
Modal Client Wrapper - Path A Only (everything in codefactoryverse, no modal_app.py)

Phase 0 (no tokens needed):
- Local mock -> uses agent_generator -> realistic chat replay with broadcast

Phase 1 (needs proxy tokens wk-/ws- + endpoint host):
Path A - Direct, everything in codefactoryverse:
  Flask -> OpenAI client -> Modal Inference Endpoint (https://inference.us-west.modal.direct)
  No modal_app.py needed, everything from codefactoryverse

Preserves Flask functionality: always returns dict that can be saved as TaskMessage.
"""
import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def _get_config():
    """Lazy load config to avoid circular imports"""
    try:
        from flask import current_app
        cfg = current_app.config
        endpoint_host = cfg.get('MODAL_ENDPOINT_HOST') or os.environ.get('MODAL_ENDPOINT_HOST')
        proxy_id = cfg.get('MODAL_PROXY_TOKEN_ID') or os.environ.get('MODAL_KEY') or os.environ.get('MODAL_PROXY_TOKEN_ID')
        proxy_secret = cfg.get('MODAL_PROXY_TOKEN_SECRET') or os.environ.get('MODAL_SECRETE') or os.environ.get('MODAL_PROXY_TOKEN_SECRET')
        proxy_auth = None
        if proxy_id and proxy_secret:
            proxy_auth = f"{proxy_id.strip()}.{proxy_secret.strip()}"
        elif os.environ.get('AUTHORIZATION'):
            proxy_auth = os.environ.get('AUTHORIZATION').replace('Bearer','').strip()
        return {
            "endpoint_host": endpoint_host,
            "proxy_auth": proxy_auth,
            "token_id": cfg.get('MODAL_TOKEN_ID') or os.environ.get('MODAL_TOKEN_ID'),
            "token_secret": cfg.get('MODAL_TOKEN_SECRET') or os.environ.get('MODAL_TOKEN_SECRET'),
        }
    except Exception:
        proxy_id = os.environ.get('MODAL_KEY') or os.environ.get('MODAL_PROXY_TOKEN_ID')
        proxy_secret = os.environ.get('MODAL_SECRETE') or os.environ.get('MODAL_PROXY_TOKEN_SECRET')
        proxy_auth = f"{proxy_id.strip()}.{proxy_secret.strip()}" if (proxy_id and proxy_secret) else None
        return {
            "endpoint_host": os.environ.get('MODAL_ENDPOINT_HOST'),
            "proxy_auth": proxy_auth or os.environ.get('AUTHORIZATION','').replace('Bearer','').strip() or None,
            "token_id": os.environ.get('MODAL_TOKEN_ID'),
            "token_secret": os.environ.get('MODAL_TOKEN_SECRET'),
        }

def _extract_requested_paths(text: str, limit: int = 3):
    """Find /workspace paths the user/agent asked to read (read-first protocol)."""
    import re
    if not text:
        return []
    found = []
    for m in re.finditer(r'(/workspace/[^\s`\)"]+)', text):
        p = m.group(1).strip().strip('`"\'`)').replace('-->', '').strip()
        if p and p not in found:
            found.append(p)
        if len(found) >= limit:
            break
    return found


def _extract_requested_names(text: str, limit: int = 3):
    """Find bare filenames near read verbs (e.g. 'read the contact.html')."""
    import re
    if not text:
        return []
    found = []
    # Quoted names first: "contact.html", `app.py`
    for m in re.finditer(r'[`"\']([A-Za-z0-9_][\w\-.]*\.[A-Za-z0-9]{1,5})[`"\']', text):
        if m.group(1) not in found:
            found.append(m.group(1))
    # 'read/open/show ... name.ext' patterns
    for m in re.finditer(r'(?i)(?:read|open|show|what.{0,10}in|content of)\s+(?:the\s+)?(?:file\s+)?([A-Za-z0-9_][\w\-.]*\.[A-Za-z0-9]{1,5})', text):
        if m.group(1) not in found:
            found.append(m.group(1))
        if len(found) >= limit:
            break
    return found[:limit]


def _fulfill_sandbox_reads(text: str, sandbox_id: str, limit: int = 3) -> str:
    """Backend read-through: actually call read_file_from_sandbox for requested
    paths so the agent answers from real contents (works even in local-mock mode).

    Handles exact /workspace paths AND bare filenames (resolved via find_file).
    Returns a markdown evidence block (empty when nothing requested or no sandbox).
    Never raises - failures become a readable note, never a crash.
    """
    if not text or not sandbox_id or sandbox_id.startswith("sb-mock-") or sandbox_id.startswith("sb-error-"):
        return ""
    try:
        from app.services.modal_sandbox_service import read_file_from_sandbox, find_file_in_sandbox
    except Exception as e:
        return f"\n## Sandbox Reads (backend could not load service: {e})\n"
    targets = []
    for p in _extract_requested_paths(text, limit=limit):
        targets.append(p)
    for name in _extract_requested_names(text, limit=limit):
        if name not in targets and f"/workspace/{name}" not in targets:
            try:
                found = find_file_in_sandbox(sandbox_id, name)
                matches = (found or {}).get("matches", []) or []
            except Exception:
                matches = []
            if matches:
                targets.append(matches[0])
            else:
                targets.append(f"/workspace/{name}")
    targets = targets[:limit]
    if not targets:
        return ""
    lines = ["\n## Sandbox Reads (backend fulfilled via read_file_from_sandbox)"]
    for p in targets:
        try:
            res = read_file_from_sandbox(sandbox_id, p)
            content = (res or {}).get("content", "")
            if content is None:
                content = ""
            if not content:
                lines.append(f"\n### {p}\nFile not found or empty at this path.")
            else:
                lines.append(f"\n### {p} ({len(content)} chars)\n```\n{content[:4000]}\n```")
        except Exception as e:
            lines.append(f"\n### {p}\nRead failed: {e}")
    return "\n".join(lines)


def run_agent_via_modal_endpoint(task_title: str, briefing: str, full_prompt: str,
                                 agent_name: str, role: str, skills: list, system_prompt: str,
                                 endpoint_host: str, proxy_auth: str, task_id: int = None,
                                 chat_history: str = None, sandbox_context: str = "",
                                 sandbox_id: str = None) -> Dict[str, Any]:
    """
    Path A - Direct, everything in codefactoryverse:
    Calls Modal Inference Endpoint directly via OpenAI-compatible client.
    
    Needs:
      - MODAL_ENDPOINT_HOST = e.g. my-qwen--qwen3-8b-xxx.modal.run or my-endpoint.us-west.modal.direct
      - MODAL_PROXY_TOKEN = wk-...ws-... (from https://modal.com/settings/proxy-tokens)
    
    Uses Affinity Routing: Modal-Routing-Affinity-Key = task-{id} for KV-cache reuse.
    """
    try:
        from openai import OpenAI

        if endpoint_host.startswith("http"):
            base_url = endpoint_host.rsplit("/v1", 1)[0] + "/v1" if "/v1" not in endpoint_host else endpoint_host
            model_name = endpoint_host.split("//")[-1].split("http://")[-1].split("/")[0]
            if ".modal.run" in endpoint_host or ".modal.direct" in endpoint_host:
                model_name = endpoint_host.split("https://")[-1].split("http://")[-1].split("/")[0]
        else:
            base_url = "https://inference.us-west.modal.direct/v1"
            model_name = endpoint_host

        if ".modal.run" in model_name and not model_name.startswith("http"):
            base_url = f"https://{model_name}/v1"

        client = OpenAI(base_url=base_url, api_key=proxy_auth)

        skill_str = ", ".join([s.get('name', s.get('id','')) if isinstance(s, dict) else str(s) for s in skills[:5]]) if skills else "coding, planning"

        system_content = f"""{system_prompt}

You are {agent_name}, role: {role}.
Skills: {skill_str}
Personality: {role} specialist.
Principles: Think step-by-step, plan before coding, write tests first, document reasoning.
You have read all previous chats in this task - all bots share chat history.

CRITICAL SANDBOX KNOWLEDGE - READ FROM SANDBOX FIRST (MOST IMPORTANT SKILL):
- /workspace is the ONLY place you work: the live Modal sandbox filesystem for this project.
- READ skill (use these exact tools when the user says "read the file X"):
  * list_files_in_sandbox(sandbox_id, path="/workspace") -> {{"files": [...]}} - see what exists
  * find_file_in_sandbox(sandbox_id, filename) -> {{"matches": [...]}} - locate a bare filename like contact.html
  * read_file_from_sandbox(sandbox_id, remote_path) -> {{"content": "...", "remote_path": ...}} - read exact content
    async form: await read_file_from_sandbox_async(sandbox_id, remote_path)
  * write_text_to_sandbox(sandbox_id, content, remote_path) -> write text directly
  * upload_file_to_sandbox(sandbox_id, local_path, remote_path) -> send a local file
- HOW TO ANSWER "read the file /workspace/X and tell me what's in there":
  1. Call the find/list/read tool for that exact path (do not guess contents).
  2. Quote/summarize the returned content in your reply.
  3. If the tool result is already shown in SANDBOX READS below, use THAT content.
  4. NEVER write a helper script (e.g. _read_contact_helper.py) to locate or print
     a file - call the read tool instead. Helper scripts cannot show you contents.
- MATCH THE ACTION TO THE REQUEST - do not always create code:
  * "delete/remove the file X" -> call delete_file_in_sandbox, then confirm. Do NOT generate replacement code.
  * "test / check / run X" -> call exec_command_in_sandbox (e.g. ls, cat, pytest), report the output. Do NOT rewrite the file.
  * "read X" -> read tool only, no new code.
  * Only generate new code blocks when the user asked for new/changed code.
- NEVER invent a function called read_files. Only list_files_in_sandbox and
  read_file_from_sandbox exist. If you need a file read, name the exact
  /workspace path instead of inventing a helper.
- You cannot execute code yourself. Emit the exact Execute-button file block
  (# File: /workspace/... plus File to create arrow) and ask the user to click
  Execute in Sandbox, or state the exact read path you need.
- When you generate code, ALWAYS specify file path in /workspace, e.g. /workspace/app.py, /workspace/src/Header.tsx
- User can click Execute button in chat to make your changes to sandbox - your code will be written to /workspace and executed
- Check what's in /workspace before writing: list files first, then read the file under test

When you respond, first give a 1-2 sentence briefing (visible in chat list), then detailed plan/code/logs (hidden behind + button).
Task Context: Title: {task_title}
"""

        chat_section = f"\n\nRecent Chat History (all bots have read this, last 20 messages):\n{chat_history[:4000]}\n" if chat_history else ""

        sandbox_section = f"\n\n{sandbox_context}\n" if sandbox_context else ""

        user_content = f"""Briefing: {briefing}

Full Prompt / Requirements:
{full_prompt[:4000] if full_prompt else 'No additional requirements'}
{chat_section}{sandbox_section}
Provide:
1. Short briefing (1-2 sentences) referencing previous chats if relevant
2. Detailed execution log with code, plan, verification
3. Mention which other bots' messages you have read
4. Specify exact file paths in /workspace where your code should go, so user can click Execute to make changes to sandbox
"""

        extra_headers = {}
        if task_id:
            extra_headers["Modal-Routing-Affinity-Key"] = f"task-{task_id}"

        # Sandbox tools the model can actually call (real reads, not prose).
        tools = None
        if sandbox_id and not str(sandbox_id).startswith("sb-mock-") and not str(sandbox_id).startswith("sb-error-"):
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "list_files_in_sandbox",
                        "description": "List files in the Modal sandbox /workspace. Call this first to see what exists.",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string", "description": "Directory, default /workspace"}},
                            "required": [],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "find_file_in_sandbox",
                        "description": "Locate a bare filename under /workspace. Use when the user names a file without a path.",
                        "parameters": {
                            "type": "object",
                            "properties": {"filename": {"type": "string", "description": "Bare filename, e.g. contact.html"}},
                            "required": ["filename"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "read_file_from_sandbox",
                        "description": "Read exact text content of a /workspace file. Use when the user asks what is in a file.",
                        "parameters": {
                            "type": "object",
                            "properties": {"remote_path": {"type": "string", "description": "Exact /workspace path, e.g. /workspace/app.py"}},
                            "required": ["remote_path"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "delete_file_in_sandbox",
                        "description": "Delete a /workspace file. Use when the user asks to delete/remove a file - do NOT create code instead.",
                        "parameters": {
                            "type": "object",
                            "properties": {"remote_path": {"type": "string", "description": "Exact /workspace path to delete"}},
                            "required": ["remote_path"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "exec_command_in_sandbox",
                        "description": "Run a shell command in the sandbox (ls, cat, python tests, pytest). Use when the user asks to test/check/run something without creating new code.",
                        "parameters": {
                            "type": "object",
                            "properties": {"command": {"type": "string", "description": "Shell command, e.g. ls -la /workspace or python -m pytest tests/ -v"}},
                            "required": ["command"],
                        },
                    },
                },
            ]

        def _call_tools(tool_calls):
            import json as _json
            results = []
            for tc in tool_calls:
                name = (tc.function.name if hasattr(tc, "function") else tc.get("function", {}).get("name")) or ""
                raw_args = (tc.function.arguments if hasattr(tc, "function") else tc.get("function", {}).get("arguments")) or "{}"
                try:
                    args = _json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except Exception:
                    args = {}
                try:
                    if name == "list_files_in_sandbox":
                        from app.services.modal_sandbox_service import list_files_in_sandbox as _ls
                        out = _ls(sandbox_id, args.get("path") or "/workspace")
                        files = (out or {}).get("files", []) if isinstance(out, dict) else []
                        shown = [f.get("path", f.get("name")) for f in files[:30] if isinstance(f, dict)]
                        results.append((tc, f"files ({len(files)}): " + (", ".join(shown) if shown else "(empty)")))
                    elif name == "find_file_in_sandbox":
                        from app.services.modal_sandbox_service import find_file_in_sandbox as _find
                        out = _find(sandbox_id, args.get("filename", ""))
                        matches = (out or {}).get("matches", []) or []
                        results.append((tc, "matches: " + (", ".join(matches) if matches else "(not found under /workspace)")))
                    elif name == "read_file_from_sandbox":
                        from app.services.modal_sandbox_service import read_file_from_sandbox as _rd
                        out = _rd(sandbox_id, args.get("remote_path", ""))
                        content_out = (out or {}).get("content", "") or ""
                        results.append((tc, content_out[:6000] if content_out else "(empty file)"))
                    elif name == "delete_file_in_sandbox":
                        from app.services.modal_sandbox_service import delete_file_in_sandbox as _dl
                        out = _dl(sandbox_id, args.get("remote_path", ""))
                        if isinstance(out, dict) and out.get("deleted"):
                            results.append((tc, f"deleted {out.get('remote_path')}"))
                        else:
                            results.append((tc, f"delete failed: {(out or {}).get('error', 'unknown error')}"))
                    elif name == "exec_command_in_sandbox":
                        from app.services.modal_sandbox_service import exec_command_in_sandbox as _ex
                        out = _ex(sandbox_id, args.get("command", ""))
                        output = (out or {}).get("output", "") or ""
                        results.append((tc, f"exit={ (out or {}).get('returncode')} output:\n{output[:4000]}"))
                    else:
                        results.append((tc, f"unknown tool: {name}"))
                except Exception as e:
                    results.append((tc, f"tool {name} failed: {e}"))
            return results

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
        tool_evidence = []
        content = ""
        for _round in range(4):
            kwargs = dict(model=model_name, messages=messages, max_tokens=5000, temperature=0.7,
                          extra_headers=extra_headers if extra_headers else None)
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            try:
                resp = client.chat.completions.create(**kwargs)
            except TypeError:
                # Older OpenAI-compatible endpoint without tools support: retry plain
                resp = client.chat.completions.create(
                    model=model_name, messages=messages, max_tokens=5000,
                    temperature=0.7, extra_headers=extra_headers if extra_headers else None)
                tools = None
            msg = resp.choices[0].message
            content = msg.content or content or ""
            calls = getattr(msg, "tool_calls", None) or []
            if not calls or not tools:
                break
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in calls]})
            for tc, output in _call_tools(calls):
                tool_evidence.append(f"### {tc.function.name}({tc.function.arguments}) -> {len(output)} chars\n```\n{output[:4000]}\n```")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})
        if not content:
            content = "Sandbox tools executed; see Sandbox Reads below." if tool_evidence else ""
        lines = content.strip().split("\n") if content.strip() else []
        briefing_out = lines[0].strip()[:300] if lines else (content[:200] if content else briefing[:300])

        reads_block = ""
        if tool_evidence:
            reads_block = "\n## Sandbox Reads (tool calls fulfilled by backend)\n" + "\n".join(tool_evidence) + "\n"

        # Stored log stays lean: input echoes are trimmed (they get re-sent as
        # context on later runs, so bloated echoes squeeze the reply). The full
        # LLM response and sandbox reads are always kept whole.
        full_log = f"""# Agent {agent_name} - Real LLM via Modal Endpoint

**Model:** {model_name}
**Endpoint:** {endpoint_host}
**Base URL:** {base_url}
**Affinity:** task-{task_id}

**Role:** {role}
**Task:** {task_title}
**Skills:** {skill_str}

## Briefing Input
{briefing[:1000]}

## Full Prompt (trimmed echo)
```
{full_prompt[:2000]}
```

## LLM Response (Full)
{content}
{reads_block}
## Verification
- Generated via Modal Inference Endpoint (Path A, everything in codefactoryverse)
- Affinity routing key: task-{task_id}
- Model: {model_name}
"""
        if len(full_log) > 15000:
            full_log = full_log[:15000] + "\n...[stored log trimmed at 15000 chars, LLM response above is complete]...\n"

        return {
            "briefing": briefing_out,
            "full_log": full_log,
            "message_type": "chat",
            "status": "idle",
            "returncode": 0,
            "source": f"modal-endpoint-direct ({model_name})",
            "model_used": model_name
        }

    except Exception as e:
        logger.warning(f"Modal Endpoint direct call failed {endpoint_host}: {e}")
        return None

def _get_task_chat_history(task_obj, limit: int = 20) -> str:
    """Get recent chat history for agent context - so all bots read previous chats"""
    try:
        from app.models import TaskMessage
        messages = task_obj.messages.order_by(TaskMessage.created_at.desc()).limit(limit).all()
        messages = list(reversed(messages))
        lines = []
        for m in messages[-limit:]:
            author = ""
            if m.agent:
                author = m.agent.name
            elif m.author:
                author = m.author.username
            else:
                author = m.role
            lines.append(f"[{m.created_at.strftime('%H:%M')}] {author} ({m.role}): {m.content[:200]}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to get chat history: {e}")
        return ""

def run_agent_local_mock(task_title: str, briefing: str, full_prompt: str, agent_name: str, role: str, skills: list, model: str, task_id: int = None, extra_context: Dict = None) -> Dict[str, Any]:
    """Fallback that generates realistic chat without needing Modal - now includes chat history"""
    from .agent_generator import generate_agent_response
    ctx = {
        "task_id": task_id,
        "model_endpoint": "local-mock",
        "proxy_auth": None,
    }
    if extra_context:
        ctx.update(extra_context)
        if "chat_history" not in ctx:
            try:
                task_obj = extra_context.get("task_obj")
                if task_obj:
                    ctx["chat_history"] = _get_task_chat_history(task_obj)
            except:
                pass

    result = generate_agent_response(
        task_title=task_title,
        briefing=briefing,
        full_prompt=full_prompt,
        agent_name=agent_name,
        role=role,
        skills=skills,
        model=model,
        context=ctx
    )
    result["source"] = "local-mock-with-history"
    result["returncode"] = 0
    return result

def run_agent_factory(task_obj, agent_obj, extra_context: Dict = None) -> Dict[str, Any]:
    """
    Main entrypoint called from Flask agents/routes.py
    Returns dict with briefing, full_log, message_type
    Attempt order:
    1. Path A - If MODAL_ENDPOINT_HOST + proxy_auth set -> direct call to Modal Inference Endpoint (everything in codefactoryverse)
    2. Local mock with rich generator - always works
    """
    cfg = _get_config()
    task_title = task_obj.title
    briefing = task_obj.description or task_title
    full_prompt = task_obj.full_prompt or ""
    agent_name = agent_obj.name
    role = agent_obj.role
    skills = agent_obj.get_skills()
    model = agent_obj.model or "prime-v1"
    system_prompt = agent_obj.system_prompt

    chat_history = _get_task_chat_history(task_obj, limit=20)

    # === SANDBOX CONTEXT - Master Agent must know what's sandbox created for project ===
    sandbox_context = ""
    sandbox_info_dict = {}
    try:
        from app.models import ProjectSandbox
        # 1 sandbox per project for now
        sandbox = ProjectSandbox.query.filter_by(project_id=task_obj.project_id).first()
        if sandbox:
            sandbox_info_dict = {
                "name": sandbox.name,
                "type": sandbox.type,
                "runtime": sandbox.runtime,
                "status": sandbox.status,
                "id": sandbox.modal_sandbox_id,
                "tunnel_url": sandbox.tunnel_url,
                "volume_name": sandbox.volume_name,
                "is_alive": sandbox.is_alive(),
                "git_repo_url": sandbox.git_repo_url,
                "dev_command": sandbox.dev_command,
            }
            # Build context string for agent prompt (canonical backend verb names)
            sandbox_context = f"""
SANDBOX CREATED FOR THIS PROJECT (per-project, no volume, filesystem API):
- Name: {sandbox.name}
- Type: {sandbox.type} ({sandbox.runtime})
- Status: {sandbox.status} - {'alive' if sandbox.is_alive() else 'expired/not alive'}
- ID: {sandbox.modal_sandbox_id or 'none (mock)'}
- Tunnel URL: {sandbox.tunnel_url or 'no tunnel yet - waiting for establishment'}
- Volume: {sandbox.volume_name} (legacy field, not used - using filesystem API directly)
- Git Repo: {sandbox.git_repo_url or 'not set'}
- Dev Command: {sandbox.dev_command or 'not set'}
- Files are in /workspace per-project path, shared across tasks in same project
- READ FIRST: list_files_in_sandbox(sandbox_id, "/workspace"), then read_file_from_sandbox(sandbox_id, remote_path)
- WRITE: write_text_to_sandbox(sandbox_id, content, remote_path) or upload_file_to_sandbox(sandbox_id, local_path, remote_path)
- NEVER invent read_files. Only the verbs above exist.
- Example: Read /workspace/app.py first, then write to /workspace/app.py via Execute button
- User can click Execute button in chat to make your changes to sandbox - specify exact file paths
"""
            # Best-effort live file snapshot so the agent sees real /workspace content
            if sandbox and sandbox.modal_sandbox_id and not sandbox.modal_sandbox_id.startswith("sb-mock-"):
                try:
                    from app.services.modal_sandbox_service import list_files_in_sandbox as _ls
                    snap = _ls(sandbox.modal_sandbox_id, "/workspace")
                    files = (snap or {}).get("files", []) if isinstance(snap, dict) else []
                    if files:
                        shown = ", ".join([f.get("path", f.get("name", "?")) for f in files[:20] if isinstance(f, dict)])
                        sandbox_context += f"\n- Live /workspace snapshot ({len(files)} files): {shown}"
                    else:
                        sandbox_context += "\n- Live /workspace snapshot: (empty or unreadable - treat as empty and ask for Execute)"
                except Exception as snap_e:
                    logger.warning(f"Sandbox file snapshot failed for {sandbox.modal_sandbox_id}: {snap_e}")
        else:
            sandbox_context = "No sandbox for this project yet. Create one with +Add Sandbox (basic modal) and ports 8000,5173 for tunnel."
    except Exception as e:
        logger.warning(f"Failed to get sandbox context for task {task_obj.id}: {e}")
        sandbox_context = f"Error getting sandbox info: {e}"
        sandbox = None

    # Backend read-through: if the user asked to read /workspace paths, fetch the
    # real contents now so EVERY agent (endpoint or local mock) answers from them.
    try:
        _sb_id = (sandbox.modal_sandbox_id if sandbox else None) or ""
        _reads = _fulfill_sandbox_reads(f"{briefing}\n{full_prompt}", _sb_id)
        if _reads:
            sandbox_context += f"\n{_reads}\n"
    except Exception as e:
        logger.warning(f"Sandbox read-through failed: {e}")

    # Path A - Direct: Try Modal Inference Endpoint directly
    if cfg.get("endpoint_host") and cfg.get("proxy_auth"):
        result = run_agent_via_modal_endpoint(
            task_title=task_title,
            briefing=briefing,
            full_prompt=full_prompt,
            agent_name=agent_name,
            role=role,
            skills=skills,
            system_prompt=system_prompt,
            endpoint_host=cfg["endpoint_host"],
            proxy_auth=cfg["proxy_auth"],
            task_id=task_obj.id,
            chat_history=chat_history,
            sandbox_context=sandbox_context,
            sandbox_id=(sandbox.modal_sandbox_id if sandbox else None)
        )
        # Inject sandbox context into result's full_log if needed
        if result and sandbox_context:
            result['full_log'] = f"{sandbox_context}\n\n{result.get('full_log','')}"
            # Also add to briefing? No, keep briefing short
        if result:
            return result

    # Fallback local mock - always works
    if extra_context is None:
        extra_context = {}
    extra_context["chat_history"] = chat_history
    extra_context["task_obj"] = task_obj
    extra_context["sandbox_context"] = sandbox_context
    extra_context["sandbox_info"] = sandbox_info_dict

    return run_agent_local_mock(
        task_title=task_title,
        briefing=briefing,
        full_prompt=full_prompt,
        agent_name=agent_name,
        role=role,
        skills=skills,
        model=model,
        task_id=task_obj.id,
        extra_context=extra_context
    )
