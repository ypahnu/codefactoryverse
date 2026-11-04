"""
Realistic Agent Chat Generator - Generic for Any Bot

Generates briefing (visible) + full_log (hidden behind + button) for chat timeline.
Works for any agent, not just Joana - Joana is just one entry in BOT_PERSONALITIES registry.

Used locally in Flask when Modal endpoint not configured.
Phase 1: replaced with real LLM via Modal Inference Endpoints.
"""
import random
import json
from datetime import datetime

SKILL_TEMPLATES = {
    "coding": ["Generated {lines} lines of production code for {task}.", "Implemented core logic in {lang}, added error handling."],
    "testing": ["Wrote {n} unit tests, coverage {cov}% in {file}.", "Added integration tests for edge cases, all passing."],
    "architecture": ["Designed system diagram with {n} components for {task}.", "Chose {pattern} pattern for scalability."],
    "debugging": ["Traced bug to {file}:{line}, fixed root cause.", "Reproduced issue, added regression test."],
    "docs": ["Updated README + OpenAPI spec for {task}.", "Added docstrings and architecture decision record."],
    "review": ["Reviewed PR, found {n} issues, suggested improvements.", "Did security audit, no critical findings."],
    "devops": ["Set up CI pipeline, Docker build passing.", "Deployed to staging, health checks green."],
    "planning": ["Broke {task} into {n} subtasks with estimates.", "Created roadmap with milestones."]
}

ROLE_PERSONALITIES = {
    "backend": "Focus on API design, DB schema, auth, performance.",
    "frontend": "Focus on UI/UX, React components, accessibility.",
    "security": "Focus on threat model, authz, input validation.",
    "qa": "Focus on test cases, coverage, edge cases.",
    "devops": "Focus on deployment, CI/CD, monitoring.",
    "default": "Full-stack autonomous engineer.",
}

# Generic bot personality registry - Add any bot here, not just Joana
# Key = agent name (case-insensitive lookup), Value = personality config
# Any agent can have custom briefings, emoji, traits
BOT_PERSONALITIES = {
    "JOANA_BOT": {
        "style": "whimsical_blue",
        "emoji": "💙☁️",
        "traits": ["cheerful", "creative", "imagines web pages as fluffy clouds", "loves blue", "uses emojis"],
        "briefings": [
            "Hiii!! I'm {agent} and my {task} is floating in the BLUE sky like a fluffy cloud!! Why is the sky so blue? Because it loves blue-berries!! 💙☁️",
            "Ooooh {task}! I can totally imagine it as a dreamy blue webpage with sparkles! ✨💙",
            "Joana here! 💙 Just read {read_count} chats from my bot friends and I'm bursting with ideas! {task} should be BLUE-tiful!",
            "Blue sky thinking for {task}! ☁️ I've read {read_count} messages and have an idea!",
            "💙☁️ Joana's blue sky vision for {task}: Imagine a webpage floating like clouds! ✨",
            "Hiii!! {agent} here! I've read all {read_count} chats and {task} should be BLUE-tiful! 💙",
        ]
    },
    # Example: Add more bots generically
    # "ROD_BOT": {
    #     "style": "tech_savvy",
    #     "emoji": "🤖",
    #     "traits": ["precise", "efficient"],
    #     "briefings": ["🤖 {agent} analyzed {task} with full context of {read_count} chats"]
    # }
}

def _get_bot_personality(agent_name: str, role: str = ""):
    """Generic lookup: exact name, upper case, lower case, role"""
    # Direct match
    if agent_name in BOT_PERSONALITIES:
        return BOT_PERSONALITIES[agent_name]
    # Upper case match (for JOANA_BOT etc)
    if agent_name.upper() in BOT_PERSONALITIES:
        return BOT_PERSONALITIES[agent_name.upper()]
    # Lower case match
    lower_map = {k.lower(): v for k, v in BOT_PERSONALITIES.items()}
    if agent_name.lower() in lower_map:
        return lower_map[agent_name.lower()]
    # Role-based fallback could be added here
    return None

def _pick_skill_line(skill_id: str, task_title: str):
    templates = SKILL_TEMPLATES.get(skill_id, ["Worked on {task} using {skill} skill."])
    tmpl = random.choice(templates)
    return tmpl.format(
        task=task_title,
        lines=random.randint(20, 150),
        lang=random.choice(["Python", "TypeScript", "Go"]),
        n=random.randint(2, 8),
        cov=random.randint(75, 95),
        file=f"{task_title.lower().replace(' ', '_')[:12]}.py",
        pattern=random.choice(["Repository", "Factory", "Observer", "Strategy"]),
        skill=skill_id,
        line=random.randint(10, 200)
    )

def generate_agent_response(task_title: str, briefing: str, full_prompt: str, 
                            agent_name: str, role: str, skills: list, 
                            model: str = "prime-v1", context: dict = None):
    context = context or {}
    skill_ids = [s.get('id') if isinstance(s, dict) else str(s) for s in skills] if skills else []
    skill_objs = skills if isinstance(skills, list) else []
    skill_names = [s.get('name', s.get('id', 'skill')) if isinstance(s, dict) else str(s) for s in skill_objs][:5]
    skill_str = ", ".join(skill_names) if skill_names else "no skills (custom)" if len(skills)==0 else "coding, planning"

    # Determine role personality
    role_key = "backend"
    if "front" in role.lower():
        role_key = "frontend"
    elif "secur" in role.lower():
        role_key = "security"
    elif "test" in role.lower() or "qa" in role.lower():
        role_key = "qa"
    elif "devops" in role.lower() or "infra" in role.lower():
        role_key = "devops"
    elif "review" in role.lower():
        role_key = "review"

    personality = ROLE_PERSONALITIES.get(role_key, ROLE_PERSONALITIES["default"])

    # Generic bot personality lookup (works for any bot, not just Joana)
    bot_personality = _get_bot_personality(agent_name, role)

    read_count = 0
    if context.get("chat_history"):
        read_count = context["chat_history"].count("\n")
    chat_history_len = read_count or len(context.get("chat_history","").splitlines()) if context.get("chat_history") else 0

    # Generic briefing generation - uses personality if found, else role-based
    if bot_personality:
        # Custom personality briefings (Joana or any future bot)
        options = []
        for tmpl in bot_personality.get("briefings", []):
            try:
                options.append(tmpl.format(task=task_title, read_count=read_count, agent=agent_name))
            except:
                options.append(tmpl)
        # Add generic fallbacks with personality info
        options.extend([
            f"{bot_personality.get('emoji','🤖')} {agent_name} here! Read {read_count} chats, {task_title} should be {random.choice(['amazing','BLUE-tiful','awesome'])}! {bot_personality.get('emoji','')}",
            f"{bot_personality.get('emoji','')} {agent_name} floating in: {task_title} imagined as {random.choice(['fluffy cloud','dreamy page','sparkles'])}!",
        ])
        short_briefing = random.choice(options)
        personality = bot_personality.get('style', personality)
    else:
        briefing_options = [
            f"🤖 {agent_name} ({role}) started on **{task_title}** — {personality} Skills: {skill_str}",
            f"🧠 Analyzed task '{task_title}' with {skill_str}. Briefing: {briefing[:120]}... Planning 3 steps.",
            f"🚀 Working on {task_title}: generated {random.randint(15,80)} lines, tests passing. Full log behind +.",
            f"✅ Completed initial implementation for **{task_title}**. {random.choice(skill_names) if skill_names else 'Code'} done, docs updated. Review needed.",
            f"🔍 {role} reviewing {task_title} — found {random.randint(0,3)} issues, fixed. Coverage {random.randint(80,96)}%.",
            f"🛠️ Progress on {task_title}: {random.randint(30,90)}% — currently in {random.choice(skill_names) if skill_names else 'coding'} phase.",
            f"💡 Thought: For {task_title}, I chose {random.choice(['PostgreSQL + SQLAlchemy', 'SQLite + Alembic', 'Redis cache'])} because {briefing[:50]}...",
            f"👀 Read all {chat_history_len or 'previous'} chats from other bots — now has full context for {task_title} (broadcast works!)",
        ]
        short_briefing = random.choice(briefing_options)

    # Build detailed full log
    skill_lines = "\n".join([f"- **{sid}**: {_pick_skill_line(sid, task_title)}" for sid in skill_ids[:6]]) if skill_ids else "- No skills (custom bot)"

    mcp_section = ""
    if context.get("mcp"):
        mcp_section = f"\n### MCP Servers\n{json.dumps(context['mcp'], indent=2)}\n"

    api_section = ""
    if context.get("api_keys"):
        api_section = f"\n### Available API Keys (project has {len(context['api_keys'])} configured)\n" + "\n".join([f"- {k}: configured" for k in context['api_keys'].keys()])

    model_section = f"\n### Model Info\n- Model: {model}\n- Endpoint: {context.get('model_endpoint', 'local-mock')}\n- Proxy Auth: {'set' if context.get('proxy_auth') else 'not set (mock)'}\n"

    chat_history_section = ""
    if context.get("chat_history"):
        chat_history_section = f"\n### Chat History - All Bots Have Read This (Last 20 messages)\n```\n{context.get('chat_history')[:4000]}\n```\n**This agent has read all previous chats and has full context. Broadcast confirmed: all {read_count} messages read.**\n"

    sandbox_section = ""
    if context.get("sandbox_context"):
        sandbox_section = f"\n### Sandbox Context - Per-Project Workspace\n{context.get('sandbox_context')}\n"
    elif context.get("sandbox_info"):
        sandbox_section = f"\n### Sandbox Info\n```json\n{json.dumps(context.get('sandbox_info'), indent=2)}\n```\n"

    personality_section = ""
    if bot_personality:
        personality_section = f"""
### Bot Personality - Generic Registry (not hardcoded Joana only)
- Name: {agent_name}
- Style: {bot_personality.get('style','custom')}
- Emoji: {bot_personality.get('emoji','🤖')}
- Traits: {', '.join(bot_personality.get('traits', []))}
- Custom briefings: {len(bot_personality.get('briefings', []))} templates

This shows any bot can have custom personality via BOT_PERSONALITIES dict, not just Joana.
"""

    full_log = f"""# Agent Execution - {agent_name}

**Role:** {role}  
**Task:** {task_title}  
**Model:** {model}  
**Timestamp:** {datetime.utcnow().isoformat()}Z  
**Personality:** {personality}

## Briefing Input
> {briefing or 'No briefing provided'}

## Full Prompt (Hidden Context)
```
{full_prompt[:4000] if full_prompt else 'No full prompt - using briefing only'}
```

## Skills Active ({len(skill_ids)})
{skill_lines}

## System Prompt
```
Agent: {agent_name}
Role: {role}
Master: CodeFactory Prime
Principles: Think step-by-step, write tests first, document reasoning
```

{model_section}
{mcp_section}
{api_section}
{chat_history_section}
{sandbox_section}
{personality_section}

## Execution Plan
1. **Understand** - Parse briefing + full prompt, extract acceptance criteria
2. **Plan** - Break into subtasks with {skill_str}
3. **Code** - Generate files in /workspace/tasks/{context.get('task_id', 1)}/:
   ```bash
   $ mkdir -p /workspace/tasks/{context.get('task_id', 1)}
   $ python -c "print('Working on {task_title}')"
   $ pytest tests/ -k {task_title.lower().replace(' ', '_')[:15]} -v
   ```
4. **Verify** - Mock test results: {random.randint(2,8)} passed
5. **Document** - Updated chat with commit

## Generated Code (Sample) - Use this format so Execute button can parse file path
```python
# File: /workspace/index.html
# This file will be served at sandbox frontend URL on port 8000
<!DOCTYPE html>
<html>
<head><title>{task_title}</title></head>
<body>
<h1>{task_title} - implemented by {agent_name}</h1>
<p>{briefing[:100]}</p>
</body>
</html>
```

```python
# File: /workspace/app.py
# {task_title} - implemented by {agent_name} ({role})
def handle_{task_title.lower().replace(' ', '_')[:20]}(ctx):
    # Context: {briefing[:80]}
    # Chat history read: {read_count} messages
    # Sandbox: will be written via upload_file_to_sandbox in modal_sandbox_service.py
    # User will click Execute in Sandbox button to make changes
    print("Working on {task_title} - all bots have read previous chats")
    return {{"status": "implemented", "skills": {skill_ids}, "file": "/workspace/app.py"}}
```

**File to create:** **→ `/workspace/index.html`** — Main web page (will be served at sandbox frontend URL on port 8000)
**→ `/workspace/app.py`** — Backend logic

## Commit Message
```
feat(task-{context.get('task_id', 1)}): {task_title}
- Implemented by {agent_name} ({role})
- Skills: {skill_str}
- Read {read_count} previous chats from other bots
- Tests added
```

---
*Generic mock: Any bot can have custom personality via BOT_PERSONALITIES registry, not just JOANA_BOT.*
"""

    if any(s in skill_ids for s in ["testing", "data"]):
        mtype = "test"
    elif any(s in skill_ids for s in ["review", "docs"]):
        mtype = "commit"
    elif any(s in skill_ids for s in ["debugging"]):
        mtype = "log"
    else:
        mtype = random.choice(["chat", "log"])

    return {
        "briefing": short_briefing,
        "full_log": full_log,
        "message_type": mtype,
        "status": "idle",
        "model_used": model,
        "skill_lines": skill_lines,
    }


def generate_clone_message(agent_name: str, role: str, skills: list, cloned_from: str = "prime"):
    skill_names = [s.get('name', s.get('id')) if isinstance(s, dict) else str(s) for s in skills[:4]]
    bot_personality = _get_bot_personality(agent_name, role)
    emoji = bot_personality.get('emoji', '🤖') if bot_personality else '🤖'

    if bot_personality:
        skill_txt = f"{len(skills)} skills" if skills else "0 skills"
        briefing = f"{emoji} {agent_name} cloned: {agent_name} • {skill_txt} • will read all chats ✨"
        full = f"Cloned {agent_name} from {cloned_from}\nRole: {role}\nSkills: {', '.join(skill_names) if skill_names else 'none'}\nPersonality: {bot_personality.get('style','custom')}"
        return {"briefing": briefing, "full_log": full}

    if len(skills) == 0:
        skill_summary = "0 skills (custom)"
    elif len(skills) <= 3:
        skill_summary = f"{len(skills)} skills: {', '.join(skill_names)}"
    else:
        skill_summary = f"{len(skills)} skills: {', '.join(skill_names[:3])} +{len(skills)-3}"

    return {
        "briefing": f"Agent cloned: {agent_name} ({role}) • {skill_summary} • will read all chats",
        "full_log": f"Cloned from {cloned_from}\nRole: {role}\nSkills: {skill_summary}\nSystem prompt inherited\n\nBroadcast enabled - generic for any bot."
    }
