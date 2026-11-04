from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Team, Project, Task, Agent, TaskMessage, MASTER_AGENT_TEMPLATE
import json
import logging

logger = logging.getLogger(__name__)

agents_bp = Blueprint('agents', __name__)

@agents_bp.route('/team/<team_slug>/<project_slug>/tasks/<int:task_id>/agents/create', methods=['POST'])
@login_required
def create(team_slug, project_slug, task_id):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    task = Task.query.filter_by(id=task_id, project_id=project.id).first_or_404()
    
    name = request.form.get('name', '').strip()
    role = request.form.get('role', '').strip()
    custom_prompt = request.form.get('system_prompt', '').strip()
    selected_skills = request.form.getlist('skills')
    voice_id = request.form.get('voice_id', '').strip()
    voice_name = request.form.get('voice_name', '').strip()
    # If voice_id provided, try to get voice_name from voices.json if not provided
    if voice_id and not voice_name:
        try:
            import json, os
            voices_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'voices', 'voices.json')
            if os.path.exists(voices_path):
                with open(voices_path) as f:
                    voices = json.load(f)
                    for v in voices:
                        if v.get('id') == voice_id:
                            voice_name = v.get('name', '')
                            break
        except:
            pass
    
    # Build skills list - FIX: allow 0 skills if user explicitly removes all
    master_skills = MASTER_AGENT_TEMPLATE['skills']
    if 'skills_present' in request.form:
        # Modal form submitted - respect exact selection, even if 0
        skills = [s for s in master_skills if s['id'] in selected_skills]
        # Allow empty list
    elif selected_skills:
        skills = [s for s in master_skills if s['id'] in selected_skills]
    else:
        # Legacy fallback: if no skills_present marker and no skills selected, default to all
        # But for new UI, skills_present will always be 1, so empty = 0 skills
        skills = master_skills if 'skills' not in request.form else []
    
    # Generate name if not provided
    if not name:
        existing_count = task.agents.count()
        name = f"{role or 'Agent'} #{existing_count+1}" if role else f"Agent #{existing_count+1}"
        if task.title[:20] not in name:
            name = f"{task.title[:15]} - {name}"
    
    # FIX: Prevent duplicate bot names in same task (case-insensitive)
    # Check existing agents in this task
    existing_names = [a.name.lower() for a in task.agents.all()]
    if name.lower() in existing_names:
        flash(f'Bot with name \"{name}\" already exists in this task! Choose a different name.', 'danger')
        return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task.id))
    # Also check for very similar names like rod vs rod2? The user said same bot twice - prevent exact duplicates, but allow rod vs rod2
    # For stricter: prevent duplicate role+name combo or warn
    # We'll also check if same role already has a bot with same base name
    base_name = name.lower().replace(' ', '').replace('-', '').replace('_', '')
    for existing in task.agents.all():
        existing_base = existing.name.lower().replace(' ', '').replace('-', '').replace('_', '')
        if base_name == existing_base:
            flash(f'Bot name too similar to existing \"{existing.name}\" in this task! Use a more distinct name.', 'warning')
            # Don't block, just warn - but in this fix we block exact duplicates only for now
            break
    
    # Use custom prompt or prepend task context to master prompt
    if not custom_prompt:
        custom_prompt = MASTER_AGENT_TEMPLATE['system_prompt'] + f"\n\nTASK CONTEXT:\nTask: {task.title}\nBriefing: {task.description}\nFull Prompt: {task.full_prompt or 'N/A'}\n\nYour specialized role for this task: {role or 'General Engineer'}"
    
    agent = Agent.create_clone(
        task_id=task.id,
        name=name,
        role=role or MASTER_AGENT_TEMPLATE['role'],
        voice_id=voice_id or None,
        voice_name=voice_name or None,
        custom_skills=skills,
        custom_prompt=custom_prompt
    )
    db.session.add(agent)
    db.session.flush()

    # === REQUEST LOGGING AS CODE (user wants to see logs when creating/sending) ===
    request_log = {
        "task_id": task.id,
        "task_title": task.title,
        "agent_name": name,
        "agent_role": role,
        "skills": [s['id'] for s in skills],
        "skills_count": len(skills),
        "system_prompt_length": len(custom_prompt),
        "cloned_from": "prime",
        "team": team.slug,
        "project": project.slug
    }
    log_code = f"""# REQUEST LOG - Create Agent Bot
# Task: {task.title} (ID {task.id})
# Project: {team.slug}/{project.slug}
# By: {current_user.username}

from app.models import Agent, Task

task = Task.query.get({task.id})

# Clone master agent CodeFactory Prime with {len(skills)} skills
agent = Agent.create_clone(
    task_id={task.id},
    name="{name}",
    role="{role}",
    custom_skills={ [s['id'] for s in skills] },
    custom_prompt=\"\"\"{custom_prompt[:200]}...\"\"\"
)

# Skills selected: {', '.join([s['name'] for s in skills]) if skills else 'none (custom)'}
# Duplicate check: {name.lower()} not in {[a.name.lower() for a in task.agents.all()]}

print(f"Created agent {{agent.name}} with {{len(skills)}} skills - will read all {task.messages.count()} previous chats")
"""
    print(log_code)
    logger.info(f"Agent creation request: {request_log}")

    # Add a system message about agent creation - now richer via generator + logs
    try:
        from app.services.agent_generator import generate_clone_message
        clone_msg = generate_clone_message(agent.name, agent.role, skills, cloned_from="prime")
        content = clone_msg["briefing"]
        # Include request log as code in full prompt for visibility
        full = clone_msg["full_log"] + f"\n\n---\n### Request Log (as code)\n```python\n{log_code}\n```\n"
    except Exception as e:
        content = f"🤖 Agent cloned: {agent.name} ({agent.role}) with {len(skills)} skills"
        full = f"Cloned from Master: {MASTER_AGENT_TEMPLATE['name']}\nSystem Prompt:\n{custom_prompt}\n\nSkills: {', '.join([s['name'] for s in skills])}\n\nRequest Log:\n{log_code}\nError: {e}"

    msg = TaskMessage(
        task_id=task.id,
        agent_id=agent.id,
        role='system',
        content=content,
        full_prompt=full,
        message_type='log'
    )
    db.session.add(msg)
    db.session.flush()

    # NEW: When new bot joins, it reads all previous chats in task (so it has full context)
    # And its creation message is broadcast to all other bots
    try:
        from app.models import MessageRead
        # New bot reads all previous messages
        for prev_msg in task.messages.all():
            if prev_msg.id == msg.id:
                continue
            existing = MessageRead.query.filter_by(message_id=prev_msg.id, agent_id=agent.id).first()
            if not existing:
                db.session.add(MessageRead(message_id=prev_msg.id, agent_id=agent.id))
        # Broadcast its own creation message to all other bots
        msg.broadcast_to_task_agents()
        db.session.commit()
    except Exception as e:
        logger.warning(f"Broadcast on clone failed: {e}")
        db.session.commit()
    
    flash(f'Agent {agent.name} cloned and synced with all {task.messages.count()} previous chats!', 'success')
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'agent': {'id': agent.id, 'name': agent.name, 'role': agent.role}})
    return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task.id))

@agents_bp.route('/team/<team_slug>/<project_slug>/tasks/<int:task_id>/agents/<int:agent_id>')
@login_required
def view(team_slug, project_slug, task_id, agent_id):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    task = Task.query.filter_by(id=task_id, project_id=project.id).first_or_404()
    agent = Agent.query.filter_by(id=agent_id, task_id=task.id).first_or_404()
    agent_messages = TaskMessage.query.filter_by(agent_id=agent.id).order_by(TaskMessage.created_at.desc()).limit(10).all()
    return render_template('agents/view.html', team=team, project=project, task=task, agent=agent, skills=agent.get_skills(), agent_messages=agent_messages)

@agents_bp.route('/team/<team_slug>/<project_slug>/tasks/<int:task_id>/agents/<int:agent_id>/delete', methods=['POST'])
@login_required
def delete(team_slug, project_slug, task_id, agent_id):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    task = Task.query.filter_by(id=task_id, project_id=project.id).first_or_404()
    agent = Agent.query.filter_by(id=agent_id, task_id=task.id).first_or_404()
    
    try:
        # Preserve chat history: orphan messages (set agent_id to NULL) instead of deleting
        # This way chat timeline keeps agent's past contributions but shows as "agent" not linked
        for msg in TaskMessage.query.filter_by(agent_id=agent.id).all():
            msg.agent_id = None
        db.session.flush()

        # Delete read receipts for this agent - broadcast feature cleanup
        # Cascade should handle this, but explicit delete is safer
        from app.models import MessageRead
        MessageRead.query.filter_by(agent_id=agent.id).delete()
        db.session.flush()

        db.session.delete(agent)
        db.session.commit()
        flash(f'Agent {agent.name} deleted - chat history preserved, read receipts cleaned', 'info')
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Failed to delete agent {agent_id}: {e}")
        flash(f'Failed to delete agent: {e}', 'danger')
    
    return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task.id))

@agents_bp.route('/team/<team_slug>/<project_slug>/tasks/<int:task_id>/agents/<int:agent_id>/run', methods=['POST'])
@login_required
def run_agent(team_slug, project_slug, task_id, agent_id):
    """Run agent - Phase 0: uses local rich generator, Phase 1: calls Modal Agent Factory endpoint if configured"""
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    task = Task.query.filter_by(id=task_id, project_id=project.id).first_or_404()
    agent = Agent.query.filter_by(id=agent_id, task_id=task.id).first_or_404()
    
    agent.status = 'working'
    # Track last active for lifespan - extend expiry on each run (heartbeat)
    try:
        agent.update_heartbeat()
    except Exception as e:
        try:
            from datetime import datetime, timezone
            agent.last_active_at = datetime.now(timezone.utc)
        except:
            pass
    db.session.commit()

    # === REQUEST LOGGING AS CODE (user wants to see logs when sending text to agent) ===
    try:
        from app.services.modal_client import _get_task_chat_history
        chat_hist = _get_task_chat_history(task, limit=10)
    except:
        chat_hist = "No history"

    request_log_code = f"""# REQUEST LOG - Send Text to Agent (Run Agent)
# Agent: {agent.name} (ID {agent.id}) - Role: {agent.role}
# Task: {task.title} (ID {task.id}) - Project: {team.slug}/{project.slug}
# Triggered by: {current_user.username}
# Time: thinking...

from app.models import Task, Agent
from app.services.modal_client import run_agent_factory

task = Task.query.get({task.id})  # {task.title}
agent = Agent.query.get({agent.id})  # {agent.name}

# Chat history that all bots have read (last 10):
\"\"\"
{chat_hist[:1000]}
\"\"\"

# Agent config:
agent_config = {{
    "name": "{agent.name}",
    "role": "{agent.role}",
    "skills": {[s['id'] for s in agent.get_skills()]},
    "model": "{agent.model}",
    "system_prompt": \"\"\"{agent.system_prompt[:200]}...\"\"\"
}}

# Extra context (MCP, API keys, models):
extra_context = {{
    "mcp": {{}},
    "api_keys": {{"MODEL_API_KEY": "set" if current_app.config.get('MODEL_API_KEY') else "not set"}},
    "models": ["{agent.model}"],
    "chat_history": chat_hist[:500] + "...",
    "triggered_by_mention": False
}}

print("🤔 Agent {agent.name} is thinking... [animated]")
result = run_agent_factory(task, agent, extra_context=extra_context)
print(f"✅ {agent.name} replied: {{result['briefing'][:100]}}")
print(f"📖 Broadcasted to {{task.agents.count()-1}} other bots - all have read it")
"""
    print(request_log_code)
    logger.info(f"Agent run request: task={task.id} agent={agent.id} {agent.name} triggered by {current_user.username}")

    try:
        # New service handles both Modal HTTP and local mock (preserves chat replay)
        from app.services.modal_client import run_agent_factory

        # Optional extra context - future: MCP, api_keys, models per project
        extra_context = {
            "mcp": {},  # TODO: load from project settings
            "api_keys": {"MODEL_API_KEY": "set" if current_app.config.get('MODEL_API_KEY') else "not set"},
            "models": [agent.model],
            "proxy_auth": current_app.config.get('modal_proxy_auth'),
        }

        result = run_agent_factory(task, agent, extra_context=extra_context)

        briefing = result.get('briefing', f"Agent {agent.name} worked on {task.title}")
        full_log = result.get('full_log', result.get('full_prompt', 'No log'))
        msg_type = result.get('message_type', result.get('type', 'chat'))
        source = result.get('source', 'unknown')

        # Enrich full_log with source info + request log as code (user wants to see logs)
        full_prompt_combined = f"""# REQUEST AS CODE (what happened)
```python
{request_log_code}
```

# RESPONSE FROM AGENT
Source: {source} | Model: {result.get('model_used', agent.model)}

{full_log}
"""

        msg = TaskMessage(
            task_id=task.id,
            agent_id=agent.id,
            role='assistant',
            content=briefing,
            full_prompt=full_prompt_combined,
            message_type=msg_type
        )
        db.session.add(msg)
        db.session.flush()

        # CRITICAL: Broadcast - all other bots in task read this chat immediately
        try:
            broadcasted = msg.broadcast_to_task_agents()
            # Author also reads own message (already counted in broadcast, but ensure)
            msg.mark_read_by_agent(agent.id)
            db.session.commit()
            logger.info(f"Broadcasted message {msg.id} to {len(broadcasted)} other bots in task {task.id}")
        except Exception as e:
            logger.warning(f"Broadcast failed: {e}")
            db.session.commit()

        agent.status = 'idle'
        db.session.commit()

        flash(f'{agent.name} replied and all {task.agents.count()-1} other bots have read it! (via {source})', 'success')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message_id': msg.id, 'briefing': briefing, 'source': source})
        return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task.id))

    except Exception as e:
        logger.exception(f"Agent run failed: {e}")
        agent.status = 'failed'
        # Fallback error message still appears in chat so UI doesn't break
        err_msg = TaskMessage(
            task_id=task.id,
            agent_id=agent.id,
            role='assistant',
            content=f"⚠️ {agent.name} failed to run: {str(e)[:150]}",
            full_prompt=f"Error trace:\n{str(e)}\n\nTask: {task.title}\nAgent: {agent.name}\nSkills: {', '.join([s['name'] for s in agent.get_skills()])}\n\nSystem:\n{agent.system_prompt[:1000]}",
            message_type='log'
        )
        db.session.add(err_msg)
        db.session.commit()
        flash(f'Agent run error: {e}', 'danger')
        return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task.id))

@agents_bp.route('/api/master-agent')
@login_required
def master_agent_info():
    """API endpoint for master agent template"""
    return jsonify(MASTER_AGENT_TEMPLATE)
