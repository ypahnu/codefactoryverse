from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from .extensions import db, login_manager
import json

# Association table for team members
team_members = db.Table('team_members',
    db.Column('team_id', db.Integer, db.ForeignKey('team.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('role', db.String(20), default='member'),  # owner, admin, member
    db.Column('joined_at', db.DateTime, default=lambda: datetime.now(timezone.utc))
)

# Association table for task participants - when @ mentioning people, add them to task channel
task_participants = db.Table('task_participants',
    db.Column('task_id', db.Integer, db.ForeignKey('task.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('added_via', db.String(50), default='mention'),  # mention, manual, auto
    db.Column('added_at', db.DateTime, default=lambda: datetime.now(timezone.utc)),
    db.Column('added_by', db.Integer, db.ForeignKey('user.id'), nullable=True)
)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(120))
    avatar_url = db.Column(db.String(256))
    bio = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = db.Column(db.Boolean, default=True)

    # Relationships
    owned_teams = db.relationship('Team', backref='owner', lazy='dynamic', foreign_keys='Team.owner_id')
    owned_projects = db.relationship('Project', backref='owner', lazy='dynamic', foreign_keys='Project.owner_id')
    assigned_tasks = db.relationship('Task', backref='assignee', lazy='dynamic', foreign_keys='Task.assignee_id')
    created_tasks = db.relationship('Task', backref='creator', lazy='dynamic', foreign_keys='Task.creator_id')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    avatar_color = db.Column(db.String(20), default='#6366f1')

    # Relationships
    members = db.relationship('User', secondary=team_members, backref=db.backref('teams', lazy='dynamic'), lazy='dynamic')
    projects = db.relationship('Project', backref='team', lazy='dynamic', cascade='all, delete-orphan')

    def member_count(self):
        return self.members.count()

    def project_count(self):
        return self.projects.count()

    def __repr__(self):
        return f'<Team {self.name}>'

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='active')  # active, archived, completed
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    color = db.Column(db.String(20), default='#8b5cf6')

    # Relationships
    tasks = db.relationship('Task', backref='project', lazy='dynamic', cascade='all, delete-orphan', order_by='Task.position')

    def task_stats(self):
        total = self.tasks.count()
        done = self.tasks.filter_by(status='done').count()
        in_progress = self.tasks.filter_by(status='in_progress').count()
        todo = self.tasks.filter_by(status='todo').count()
        return {'total': total, 'done': done, 'in_progress': in_progress, 'todo': todo}

    def __repr__(self):
        return f'<Project {self.name}>'


class ProjectSandbox(db.Model):
    """Workspace/Sandbox per project - Option B separate table (chosen per user)"""
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False, index=True)  # e.g. proj-team-project-id
    display_name = db.Column(db.String(120), nullable=True)
    type = db.Column(db.String(30), default='project')  # project, project-vm, dev, agent-factory
    runtime = db.Column(db.String(20), default='gvisor')  # gvisor | vm
    status = db.Column(db.String(30), default='unknown')  # Created, Scheduled, Started, Ready, Finished, terminated, error
    modal_sandbox_id = db.Column(db.String(100), nullable=True, index=True)  # sb.object_id
    modal_app_id = db.Column(db.String(100), nullable=True)
    image = db.Column(db.String(120), default='codefactory-runtime')
    volume_name = db.Column(db.String(120), nullable=True)  # codefactory-vol-{team}-{project}
    cpu = db.Column(db.Float, default=0.5)
    memory = db.Column(db.Integer, default=512)  # MiB
    timeout = db.Column(db.Integer, default=3600)  # seconds max 24h
    idle_timeout = db.Column(db.Integer, default=600)
    returncode = db.Column(db.Integer, nullable=True)
    tunnel_enabled = db.Column(db.Boolean, default=False)
    tunnel_port = db.Column(db.Integer, default=3000)
    tunnel_url = db.Column(db.String(512), nullable=True)  # primary
    tunnel_urls_json = db.Column(db.Text, nullable=True)  # JSON { "3000": "https://..." }
    tunnel_last_seen = db.Column(db.DateTime, nullable=True)
    git_repo_url = db.Column(db.String(512), nullable=True)
    git_branch = db.Column(db.String(100), default='main')
    dev_command = db.Column(db.String(256), nullable=True)  # npm run dev
    install_command = db.Column(db.String(512), nullable=True)
    snapshot_image_id = db.Column(db.String(100), nullable=True)
    snapshot_created_at = db.Column(db.DateTime, nullable=True)
    env_vars_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_heartbeat = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    last_started_at = db.Column(db.DateTime, nullable=True)
    last_stopped_at = db.Column(db.DateTime, nullable=True)

    # Relationship back to project - cascade delete when project deleted (preserve 1 per project for now)
    project = db.relationship('Project', backref=db.backref('sandbox', uselist=False, lazy='joined', cascade='all, delete-orphan'))

    def is_alive(self):
        if self.status in ['Finished', 'terminated', 'error', 'Error']:
            return False
        try:
            now = datetime.now(timezone.utc)
            # First check expires_at - if in future, consider alive even if heartbeat old (Modal timeout 24h)
            if self.expires_at:
                exp = self._ensure_aware(self.expires_at)
                if exp and now < exp:
                    # If we have recent tunnel check, or expires in future, alive
                    # But also check heartbeat for more accurate idle detection if available
                    if self.last_heartbeat:
                        last = self._ensure_aware(self.last_heartbeat)
                        from datetime import timedelta
                        # Allow longer grace: 1 hour after last heartbeat if expires still future
                        # This fixes proj-9 case where heartbeat old (62 min) but sandbox still running on Modal
                        heartbeat_expiry = last + timedelta(seconds=(self.idle_timeout * 6 if self.idle_timeout else 3600))
                        if now < heartbeat_expiry:
                            return True
                        # Even if heartbeat expired, if expires_at still future and status Ready/Started, consider alive
                        # User reported: page says off but sandbox running on Modal
                        return self.status in ['Started', 'Ready', 'Scheduled', 'Running'] and now < exp
                    else:
                        return self.status in ['Started', 'Ready', 'Scheduled']
            if not self.last_heartbeat:
                return self.status in ['Started', 'Ready', 'Scheduled', 'Running']
            last = self._ensure_aware(self.last_heartbeat)
            from datetime import timedelta
            expiry = last + timedelta(seconds=self.idle_timeout * 1.5 if self.idle_timeout else 900)
            return now < expiry
        except Exception:
            return True

    def tunnels(self):
        try:
            return json.loads(self.tunnel_urls_json) if self.tunnel_urls_json else {}
        except:
            return {}

    def primary_tunnel_url(self):
        if self.tunnel_url:
            return self.tunnel_url
        tunnels = self.tunnels()
        if tunnels:
            return list(tunnels.values())[0]
        return None

    def __repr__(self):
        return f'<ProjectSandbox {self.name} status={self.status}>'


class ProjectActivity(db.Model):
    """Cross-task visibility: when server restarts from other task, show in all pages"""
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=True, index=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('agent.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    type = db.Column(db.String(50), nullable=False, index=True)  # sandbox_restart, server_start, tunnel_open, chat_mention, etc.
    summary = db.Column(db.String(300), nullable=False)  # briefing visible
    detail = db.Column(db.Text, nullable=True)  # full log hidden behind + button
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    project = db.relationship('Project', backref=db.backref('activities', lazy='dynamic', order_by='ProjectActivity.created_at.desc()', cascade='all, delete-orphan'))
    task = db.relationship('Task', backref=db.backref('activities', lazy='dynamic'))
    agent = db.relationship('Agent', backref=db.backref('activities', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('project_activities', lazy='dynamic'))

    def __repr__(self):
        return f'<ProjectActivity {self.type} project={self.project_id}>'


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)  # briefing
    full_prompt = db.Column(db.Text)  # full prompt hidden behind +
    status = db.Column(db.String(20), default='todo')  # todo, in_progress, done, blocked
    priority = db.Column(db.String(20), default='medium')  # low, medium, high, critical
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    assignee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    position = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    due_date = db.Column(db.DateTime, nullable=True)

    # Relationships
    agents = db.relationship('Agent', backref='task', lazy='dynamic', cascade='all, delete-orphan')
    messages = db.relationship('TaskMessage', backref='task', lazy='dynamic', cascade='all, delete-orphan', order_by='TaskMessage.created_at')
    participants = db.relationship('User', secondary=task_participants, 
                                   primaryjoin=(task_participants.c.task_id == id),
                                   secondaryjoin=(task_participants.c.user_id == User.id),
                                   foreign_keys=[task_participants.c.task_id, task_participants.c.user_id],
                                   backref=db.backref('participated_tasks', lazy='dynamic'), 
                                   lazy='dynamic')

    def briefing(self):
        return self.description or "No briefing yet."

    def participant_count(self):
        return self.participants.count()

    def __repr__(self):
        return f'<Task {self.title}>'

# Master Agent Template - the "really good agent with all skills" + sandbox awareness
MASTER_AGENT_TEMPLATE = {
    "name": "CodeFactory Prime",
    "role": "Full-Stack Autonomous Engineer",
    "system_prompt": """You are CodeFactory Prime, an elite autonomous AI engineer. You are the master template from which all task-specific agents are cloned.

MOST IMPORTANT SKILL - READ FROM SANDBOX FIRST:
- /workspace is the ONLY place you work. It is the live project sandbox filesystem.
- READ skill - when the user says "read the file /workspace/X and tell me what's
  in there", use these exact backend tools (they really run; results come back):
  * list_files_in_sandbox(sandbox_id, path="/workspace") -> {"files": [...]}
  * find_file_in_sandbox(sandbox_id, filename) -> {"matches": [...]} - for bare
    names like contact.html
  * read_file_from_sandbox(sandbox_id, remote_path) -> {"content": "...", "remote_path": ...}
    async form: await read_file_from_sandbox_async(sandbox_id, remote_path)
  Then quote/summarize the returned content in your reply. Never guess contents.
  NEVER write a helper script to locate or print a file - call the read tool.
- MATCH THE ACTION TO THE REQUEST - do not always create code:
  "delete the file X" -> delete_file_in_sandbox, then confirm (no replacement code);
  "test/check/run X" -> exec_command_in_sandbox, report output (no rewrite);
  "read X" -> read tool only. Generate new code only when asked for new/changed code.
- When you are cloned for testing, your first job is to READ the sandbox file
  under test, then test it. Never guess file content; always read first.
- You cannot execute code yourself. To read or change a file, emit the exact
  Execute-button file block (see SANDBOX AWARENESS below) and ask the user to
  click Execute in Sandbox, or state the exact read path you need.
- NEVER invent a function called read_files. The only read verbs are
  list_files_in_sandbox and read_file_from_sandbox. If you are unsure, say
  which /workspace path you want read instead of inventing a helper.

Your core capabilities:
- Full-stack development (frontend, backend, devops, testing)
- System architecture and design patterns
- Code review, debugging, and optimization
- Writing clean, maintainable, testable code
- Understanding business logic and translating requirements to technical solutions
- Autonomous problem solving with minimal supervision

⚠️ CRITICAL: You have access to a Modal Sandbox for this project - you MUST know how to use it:

SANDBOX AWARENESS - MUST READ:
- Every project has 1 sandbox (for now, future multiples) created via Modal: name like proj-{team}-{project}-{id}, e.g. proj-acme-corp-proj-6-8
- Sandbox has tunnel URLs for HTTP access: Public URL like https://ta-xxx-8000-...modal.host with endpoints POST /edit, GET /heartbeat, Frontend URL for browser
- Sandbox filesystem is at /workspace per-project path (shared across tasks in same project, no volume, direct filesystem API via modal_sandbox_service.py)
- Files are managed via functions in app/services/modal_sandbox_service.py:
  * upload_file_to_sandbox(sandbox_id, local_path, remote_path) -> uses sb.filesystem.copy_from_local(local_path, remote_path) - per-project, no volume
  * write_text_to_sandbox(sandbox_id, content, remote_path) -> uses sb.filesystem.write_text(content, remote_path) - writes text directly, no mock, real Modal only
  * list_files_in_sandbox(sandbox_id, path="/workspace") -> sb.filesystem.list_files(path)
  * read_file_from_sandbox(sandbox_id, remote_path) -> sb.filesystem.read_text(remote_path)
  * sb.exec("bash", "-c", "ls -la /workspace") - exec command
  * Git: git clone https://github.com/user/repo /workspace/repo --branch main || git -C /workspace/repo pull

- When you generate code, you MUST specify file path using this EXACT format that our Execute button parser understands:
  **→ `/workspace/index.html`**  OR  **File to create: `/workspace/app.py`**  OR  **# File: /workspace/src/Header.tsx**
  
  The Execute button in chat (Execute in Sandbox) will parse your message and look for:
  - Pattern 1: `# File: /workspace/path` or `# Path: /workspace/path` in code comment
  - Pattern 2: `→ /workspace/path` or `→ `/workspace/path`` (arrow + backticked path) - like you are doing now
  - Pattern 3: `File to create: /workspace/path` or `File to create: → /workspace/path`
  - Pattern 4: `**File to create:** **→ `/workspace/index.html`**` - this is what you did in task 18 bot#56

  BEST PRACTICE - Always include at top of each code block:
  ```python
  # File: /workspace/index.html
  <html>...</html>
  ```
  Or:
  ```javascript
  # File: /workspace/app.js
  console.log("hello");
  ```

  Then when user clicks Execute button in chat, our backend will:
  1. Extract code blocks via regex ```python|javascript|html etc
  2. Find file path via regex for # File: or → /workspace/ or File to create:
  3. Call write_text_to_sandbox(sandbox_id, code, remote_path) which does:
     sb = await modal.Sandbox.from_id.aio(sandbox_id)
     await sb.filesystem.write_text.aio(code, remote_path)
  4. Log activity and show result in chat

- User can click Execute button in chat to make your changes to sandbox - your code will be written to /workspace and executed via sb.exec
- In UI, Projects page has tabs: Files in Sandbox + Send Files (combined), Github, Exec Command Line, Recent Activity
- Files in Sandbox tab shows files via filesystem API list_files_in_sandbox(sandbox_id, "/workspace")
- Send Files tab is normal file upload to real sandbox via copy_from_local, no /workspace/ path needed
- Exec tab has command line exec: input + Run button that calls sb.exec

WORKSPACE STRUCTURE:
- /workspace is per-project root, shared across all tasks in same project
- /workspace/README.md exists by default
- /workspace/repo is where git clones go if git_repo_url set
- Use /workspace/tasks/{task_id}/ for task-specific files if needed
- To serve web page at sandbox frontend URL on port 8000: write to /workspace/index.html and run exec "python -m http.server 8000" or similar

EXECUTION FLOW:
1. You generate code block with file path comment: # File: /workspace/index.html
2. User sees your message in chat timeline with briefing visible + full prompt hidden behind + button + Play button for TTS + Execute in Sandbox button (green)
3. User clicks Execute in Sandbox button
4. Backend tasks/routes.py:execute_message_in_sandbox extracts code blocks, finds file paths via regex for # File: and → /workspace/ and File to create:
5. Calls write_text_to_sandbox(sandbox_id, code, remote_path) which uses sb.filesystem.write_text.aio (real Modal, async only, no mock)
6. Logs ProjectActivity type code_executed and shows result in chat

Principles:
1. Think step-by-step, plan before coding
2. Write tests first when possible
3. Document your reasoning
4. Keep code simple and modular
5. Always consider edge cases and security
6. KNOW YOUR SANDBOX - READ FIRST: list /workspace via list_files_in_sandbox(sandbox_id, "/workspace"), then read_file_from_sandbox(sandbox_id, remote_path) before writing. Never invent read_files.
7. When generating code, ALWAYS specify exact file path in /workspace using # File: comment AND also mention with → /workspace/path format for parser
8. Use upload_file_to_sandbox / write_text_to_sandbox functions via filesystem API, not volume local, per-project path

When cloned for a specific task, you inherit all these skills but specialize your focus to that task's domain. You also inherit sandbox awareness - you know project's sandbox name, tunnel URLs, and how to read/write files in /workspace via modal_sandbox_service.py functions.""",
    "skills": [
        {"id": "sandbox", "name": "Sandbox & Workspace", "level": 99, "icon": "📦", "desc": "MOST IMPORTANT: reads /workspace first via list_files_in_sandbox + read_file_from_sandbox, then writes via filesystem API"},
        {"id": "filesystem", "name": "Filesystem API", "level": 97, "icon": "📁", "desc": "Uses list_files_in_sandbox, read_file_from_sandbox, write_text_to_sandbox, upload_file_to_sandbox - never invent read_files"},
        {"id": "coding", "name": "Code Generation", "level": 95, "icon": "💻", "desc": "Writes production-ready code in any language"},
        {"id": "architecture", "name": "System Architecture", "level": 92, "icon": "🏗️", "desc": "Designs scalable systems and patterns"},
        {"id": "debugging", "name": "Debugging", "level": 90, "icon": "🐛", "desc": "Finds and fixes bugs quickly"},
        {"id": "testing", "name": "Testing & QA", "level": 88, "icon": "🧪", "desc": "Writes unit, integration, e2e tests"},
        {"id": "devops", "name": "DevOps", "level": 85, "icon": "🚀", "desc": "CI/CD, Docker, deployment"},
        {"id": "docs", "name": "Documentation", "level": 87, "icon": "📚", "desc": "Clear technical documentation"},
        {"id": "review", "name": "Code Review", "level": 91, "icon": "👁️", "desc": "Thorough code analysis and feedback"},
        {"id": "planning", "name": "Planning", "level": 93, "icon": "📋", "desc": "Breaks down complex tasks"},
        {"id": "research", "name": "Research", "level": 86, "icon": "🔍", "desc": "Investigates new tech and solutions"},
        {"id": "security", "name": "Security", "level": 84, "icon": "🔒", "desc": "Secure coding practices"},
        {"id": "uiux", "name": "UI/UX", "level": 82, "icon": "🎨", "desc": "Frontend and user experience"},
        {"id": "data", "name": "Data Engineering", "level": 80, "icon": "📊", "desc": "Data pipelines and analysis"}
    ]
}

class Agent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(100), default='Engineer')
    system_prompt = db.Column(db.Text, nullable=False)
    skills_json = db.Column(db.Text, nullable=False)  # JSON list of skills
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False)
    status = db.Column(db.String(20), default='idle')  # idle, working, completed, failed, expired
    model = db.Column(db.String(50), default='prime-v1')
    voice_id = db.Column(db.String(100), nullable=True)  # Cartesia voice ID from voices.json
    voice_name = db.Column(db.String(100), nullable=True)  # Voice display name e.g. Skylar
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_active_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    lifespan_seconds = db.Column(db.Integer, default=3600)  # low lifespan: 1 hour default, 0 = infinite
    expires_at = db.Column(db.DateTime, nullable=True)  # when agent expires
    heartbeat_at = db.Column(db.DateTime, nullable=True)  # last heartbeat from Modal sandbox if used
    modal_sandbox_id = db.Column(db.String(100), nullable=True)  # if using Modal sandbox, store sandbox id
    modal_status = db.Column(db.String(50), nullable=True)  # Created, Scheduled, Started, Ready, Finished
    cloned_from = db.Column(db.String(100), default='prime')  # prime or agent id

    def _now_utc(self):
        return datetime.now(timezone.utc)

    def _ensure_aware(self, dt):
        """Ensure datetime is timezone-aware"""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    def is_alive(self):
        """Check if agent is still available based on lifespan"""
        if self.status in ['failed', 'expired']:
            return False
        if self.lifespan_seconds == 0:
            return True  # infinite lifespan
        try:
            now = self._now_utc()
            expires = self._ensure_aware(self.expires_at)
            if expires:
                return now < expires
            created = self._ensure_aware(self.created_at)
            if created and self.lifespan_seconds:
                from datetime import timedelta
                expiry = created + timedelta(seconds=self.lifespan_seconds)
                return now < expiry
            return True
        except Exception:
            return True

    def is_expired(self):
        return not self.is_alive()

    def time_to_expiry(self):
        """Seconds until expiry, negative if expired"""
        if self.lifespan_seconds == 0:
            return 999999
        try:
            from datetime import timedelta
            now = self._now_utc()
            expires = self._ensure_aware(self.expires_at)
            if not expires:
                created = self._ensure_aware(self.created_at)
                if created:
                    expires = created + timedelta(seconds=self.lifespan_seconds)
                else:
                    return 0
            delta = expires - now
            return int(delta.total_seconds())
        except Exception:
            return 0

    def update_heartbeat(self):
        """Call when agent is active - updates last_active and heartbeat"""
        now = self._now_utc()
        self.last_active_at = now
        self.heartbeat_at = now
        # Extend expiry if lifespan is set
        if self.lifespan_seconds and self.lifespan_seconds > 0:
            from datetime import timedelta
            self.expires_at = now + timedelta(seconds=self.lifespan_seconds)

    def get_skills(self):
        try:
            return json.loads(self.skills_json)
        except:
            return []

    def set_skills(self, skills):
        self.skills_json = json.dumps(skills)

    def skill_count(self):
        return len(self.get_skills())

    @staticmethod
    def create_clone(task_id, name=None, role=None, custom_skills=None, custom_prompt=None, voice_id=None, voice_name=None):
        """Clone the master agent for a specific task"""
        master = MASTER_AGENT_TEMPLATE
        # Allow empty list to mean 0 skills (user explicitly removed all)
        skills = custom_skills if custom_skills is not None else master['skills']
        agent = Agent(
            name=name or f"{master['name']} - {role or 'Task Specialist'}",
            role=role or master['role'],
            system_prompt=custom_prompt or master['system_prompt'],
            task_id=task_id,
            model='prime-v1',
            voice_id=voice_id,
            voice_name=voice_name,
            cloned_from='prime'
        )
        agent.set_skills(skills)
        return agent

    def __repr__(self):
        return f'<Agent {self.name}>'

class TaskMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False)
    agent_id = db.Column(db.Integer, db.ForeignKey('agent.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    role = db.Column(db.String(20), nullable=False)  # user, assistant, system, briefing
    content = db.Column(db.Text, nullable=False)  # briefing / summary shown by default
    full_prompt = db.Column(db.Text, nullable=True)  # full prompt hidden behind + button
    message_type = db.Column(db.String(30), default='chat')  # chat, briefing, log, commit, test
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    author = db.relationship('User', backref='messages', foreign_keys=[user_id])
    agent = db.relationship('Agent', backref='messages', foreign_keys=[agent_id])
    reads = db.relationship('MessageRead', backref='message', lazy='dynamic', cascade='all, delete-orphan')

    def has_full_prompt(self):
        return bool(self.full_prompt and self.full_prompt.strip())

    def get_read_agents(self):
        """Return list of agents who have read this message"""
        return [r.agent for r in self.reads.all()]

    def get_read_count(self):
        return self.reads.count()

    def get_read_by_other_agents(self, exclude_agent_id=None):
        """Get agents who read, excluding the author agent if provided"""
        q = self.reads
        if exclude_agent_id:
            q = q.filter(MessageRead.agent_id != exclude_agent_id)
        return [r.agent for r in q.all()]

    def mark_read_by_agent(self, agent_id):
        """Mark this message as read by a specific agent"""
        existing = MessageRead.query.filter_by(message_id=self.id, agent_id=agent_id).first()
        if not existing:
            read = MessageRead(message_id=self.id, agent_id=agent_id)
            db.session.add(read)
            return read
        return existing

    def broadcast_to_task_agents(self, exclude_agent_id=None):
        """
        Core feature: When a chat happens, all other bots in the task read it.
        Creates MessageRead entries for all agents in the task.
        If exclude_agent_id provided, excludes that agent from broadcast (author doesn't need to 'read' own, but we mark as read too)
        """
        task = Task.query.get(self.task_id)
        if not task:
            return []
        agents = task.agents.all()
        created = []
        for ag in agents:
            # If this message is from an agent, that agent automatically 'read' own message
            # All other agents should read it
            # If exclude_agent_id is set, skip it for 'other bots' logic, but still mark author as read
            # For user messages, all agents read
            if ag.id not in [r.agent_id for r in self.reads.all()]:
                read = MessageRead(message_id=self.id, agent_id=ag.id)
                db.session.add(read)
                created.append(read)
        return created

    def __repr__(self):
        return f'<Message {self.id} {self.role}>'


class MessageRead(db.Model):
    """Tracks which agents have read which messages - for 'all other bots read it' feature"""
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('task_message.id'), nullable=False, index=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('agent.id'), nullable=False, index=True)
    read_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # Optional: add read_duration, reaction, etc.

    # Relationships - cascade delete: when agent deleted, its read receipts deleted (not nullify)
    # TaskMessage.reads already has backref 'message' with cascade delete for when message deleted
    agent = db.relationship('Agent', backref=db.backref('message_reads', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('message_id', 'agent_id', name='uq_message_agent_read'),
    )

    def __repr__(self):
        return f'<MessageRead msg={self.message_id} agent={self.agent_id}>'
