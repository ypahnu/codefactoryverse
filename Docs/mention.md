# @ Mention Autocomplete - Generic for Any Bot

## Overview

User types `@` in chat textarea and sees list of agents in project and people in team. If already in task, bot answers. If not in task, bot/person added to task chat channel.

Previous implementation was hardcoded for Joana (`is_joana`, `joana_bot`). Now generic for any bot via `BOT_PERSONALITIES` registry.

## Current Implementation (After Generalization)

### Backend Data Sources

`app/blueprints/tasks/routes.py:view()` now loads:

```python
team_members = team.members.all()  # people
project_agents_all = Agent.query.join(Task, Agent.task_id == Task.id).filter(Task.project_id == project.id).all()
current_ids = [a.id for a in agents]  # agents already in this task
project_agents = [a for a in project_agents_all if a.task_id != task.id and a.name.lower() not in seen]

mention_data = {
  "inTask": [{"id": a.id, "name": a.name, "role": a.role, "type": "agent", "in_task": True, "avatar": a.name[0].upper()} for a in agents],
  "inProject": [{"id": a.id, "name": a.name, "role": a.role, "type": "agent", "in_task": False, "source_task_id": a.task_id} for a in project_agents],
  "people": [{"id": u.id, "username": u.username, "display_name": u.display_name or u.username, "type": "user"} for u in team_members]
}
```

Passed to template via `{{ mention_data|tojson }}`.

### Frontend UI

**Template `tasks/view.html`:**

```html
<div class="position-relative">
  <textarea id="chat-content-input" name="content" placeholder="... type @ to mention bots like @JOANA_BOT or people like @demo"></textarea>
  <div id="mention-dropdown" class="mention-dropdown d-none"></div>
</div>
<script id="mention-data" type="application/json">{{ mention_data|tojson }}</script>
<div class="small text-dim">
  <span>@ to mention:</span>
  <span class="badge bg-primary">{{ inTask|length }} in this task</span>
  <span class="badge bg-secondary">{{ inProject|length }} in project</span>
  <span class="badge bg-info">{{ people|length }} people</span>
</div>
```

**JS `static/js/mention.js` (new file, 200 lines):**

- `getAtQuery()` finds last `@` before cursor, captures query until cursor, checks if preceded by alphanumeric (ignore @ in middle of word)
- `filterCandidates(query)` case-insensitive filter on name/role/username, limit 5 per section
- `renderDropdown()` shows 3 sections: Agents in this task (will answer), Agents in project (will be cloned + added), People (will be added to channel)
- Keyboard: ArrowUp/Down navigate, Enter/Tab selects, Esc closes
- Click selects, replaces `@query` with `@ExactName ` and focuses textarea

**CSS `style.css`:**

```css
.mention-dropdown { position:absolute; bottom:100%; left:0; right:0; max-height:250px; overflow-y:auto; background:var(--bg2); border:1px solid var(--border); border-radius:8px; box-shadow:0 8px 24px rgba(0,0,0,0.3); z-index:1000; }
.mention-section { font-size:10px; text-transform:uppercase; color:var(--text-dim); padding:6px 10px 2px; font-weight:700; background:var(--bg3); border-top/bottom:1px solid var(--border); position:sticky; top:0; }
.mention-item { padding:6px 10px; cursor:pointer; display:flex; align-items:center; gap:8px; }
.mention-item:hover, .mention-item.active { background:rgba(99,102,241,0.15); border-left:2px solid var(--primary); }
.mention-avatar { width:24px; height:24px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:11px; color:white; }
```

### Backend Handling (Generic, Not Joana-Specific)

`tasks/routes.py:add_message()`:

```python
# Detect mentions
content_lower = content.lower()
mentioned_agents = []
for agent in task.agents.all():
    name_variants = [agent.name.lower(), agent.name.lower().replace('_',' ').replace('-',' '), agent.name.lower().replace('_bot','').strip(), agent.name.lower().split('_')[0]]
    for variant in name_variants:
        if variant and len(variant)>=3 and variant in content_lower:
            mentioned_agents.append(agent)
            break
    if f"@{agent.name.lower()}" in content_lower:
        mentioned_agents.append(agent)

# Clone agents from project if not in current task (user wants: if not had agent, add to task/chat channel)
project_agents = Agent.query.join(Task).filter(Task.project_id==project.id, Task.id != task.id).all()
for proj_agent in project_agents:
    if proj_agent.name.lower() in content_lower and proj_agent.name.lower() not in [a.name.lower() for a in task.agents.all()]:
        cloned = Agent.create_clone(task_id=task.id, name=proj_agent.name, role=proj_agent.role, custom_skills=proj_agent.get_skills(), custom_prompt=proj_agent.system_prompt)  # Keep original skills, not reselecting
        db.session.add(cloned)
        # System message: Agent cloned via @ mention from other task
        # Broadcast + new bot reads all previous chats

# Add people to task_participants (persistent, per user request "team member added to the task")
team_members = team.members.all()
for member in team_members:
    if member.username.lower() in content_lower and task.participants.filter_by(id=member.id).first() is None:
        task.participants.append(member)
        # System message: 👤 @username added to task via @ mention
```

- If inTask agent mentioned → auto-run via `run_agent_factory()` + broadcast + thinking icon
- If inProject agent mentioned not in task → clone with same skills (not reselecting) + add to task + auto-run
- If person mentioned not in participants → add to `task_participants` M2M + system message

**New model `task_participants`:**
```python
task_participants = db.Table('task_participants',
  db.Column('task_id', FK task.id, PK),
  db.Column('user_id', FK user.id, PK),
  db.Column('added_via', String default='mention'),
  db.Column('added_at', DateTime),
  db.Column('added_by', FK user.id, nullable=True)
)
Task.participants = relationship('User', secondary=task_participants, primaryjoin=(task_id==id), secondaryjoin=(user_id==User.id), foreign_keys=[task_id, user_id], backref='participated_tasks')
```

### Generic Personality (No More is_joana)

**Before (hardcoded):**
```python
if "joana" in agent_name.lower():
    # Joana-specific briefings
```

**After (generic):**
```python
BOT_PERSONALITIES = {
    "JOANA_BOT": {
        "style": "whimsical_blue",
        "emoji": "💙☁️",
        "traits": ["cheerful", "creative", "imagines web pages as fluffy clouds"],
        "briefings": ["Hiii!! I'm {agent} and my {task} is floating...", "Blue sky thinking for {task}! ..."]
    }
    # Add any bot here, e.g. "ROD_BOT": {"style": "tech_savvy", ...}
}

def _get_bot_personality(agent_name, role):
    if agent_name in BOT_PERSONALITIES: return BOT_PERSONALITIES[agent_name]
    if agent_name.upper() in BOT_PERSONALITIES: return BOT_PERSONALITIES[agent_name.upper()]
    # role-based fallback
    return None

bot_personality = _get_bot_personality(agent_name, role)
if bot_personality:
    short_briefing = random.choice([t.format(task=task_title, read_count=read_count, agent=agent_name) for t in bot_personality["briefings"]])
else:
    # generic role-based briefing
```

No more `is_joana` variable, `joana_section` replaced with generic `personality_section` using `agent_name` dynamically and `other_bots = ", ".join([a.name for a in task_agents if a.name != agent_name][:3])` instead of hardcoded "peter and others".

### Test Flow

1. In Task 5 with peter + JOANA_BOT, type `@` in textarea → dropdown shows 2 in task, X in project, Y people filtered as you type after @
2. Type `@jo` → filters to JOANA_BOT only
3. Select JOANA_BOT → inserts `@JOANA_BOT ` → submit → Joana auto-replies with blue sky thinking, broadcast to all, read receipts
4. Type `@rod` where rod is in other task (task2) but not current → clones rod into current task with same skills (no reselect), system log "Agent cloned via @ mention from other task", then auto-replies
5. Type `@demo` (person) → adds demo to `task_participants`, system message "👤 @demo added to task"

### Files Modified

- `models.py` - add `task_participants` table + relationship + generic personality fields
- `agent_generator.py` - remove 23 `joana` hardcoded matches, replace with `_get_bot_personality()` generic, BOT_PERSONALITIES dict data-driven
- `tasks/routes.py:view()` - load team_members + project_agents + mention_data JSON
- `tasks/routes.py:add_message()` - enhance mention detection to clone project agents (keep skills) and add people to participants
- `templates/tasks/view.html` - add position-relative wrapper, mention-dropdown div, mention-data script, badges for counts
- `static/js/mention.js` - new file 200 lines for autocomplete
- `static/css/style.css` - add mention-dropdown styles

### Future Improvements

- Add `personality_style` column to Agent model to allow custom personality per agent without code change
- Add `briefing_templates_json` to store custom templates per agent
- Replace substring matching with stricter `@Name` regex to avoid false positives
- Add WebSocket for real-time dropdown updates when new agents join
- Add email notification when person added via @ mention

Date: 2026-10-27
Status: Implemented generic, Joana now just one entry in registry
