from flask import Blueprint, render_template
from flask_login import login_required, current_user
from app.models import Team, Project, Task

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@login_required
def index():
    # Get user's teams
    teams = current_user.teams.all() if hasattr(current_user.teams, 'all') else list(current_user.teams)
    # Recent projects from user's teams
    team_ids = [t.id for t in teams]
    recent_projects = Project.query.filter(Project.team_id.in_(team_ids)).order_by(Project.updated_at.desc()).limit(6).all() if team_ids else []
    # Recent tasks
    my_tasks = Task.query.filter_by(assignee_id=current_user.id).order_by(Task.updated_at.desc()).limit(5).all()
    created_tasks = Task.query.filter_by(creator_id=current_user.id).order_by(Task.created_at.desc()).limit(5).all()
    
    stats = {
        'teams': len(teams),
        'projects': Project.query.filter(Project.team_id.in_(team_ids)).count() if team_ids else 0,
        'tasks_todo': Task.query.filter(Task.project_id.in_([p.id for p in recent_projects]), Task.status=='todo').count() if recent_projects else 0,
        'tasks_done': Task.query.filter(Task.project_id.in_([p.id for p in recent_projects]), Task.status=='done').count() if recent_projects else 0,
    }
    return render_template('dashboard/index.html', teams=teams, recent_projects=recent_projects, my_tasks=my_tasks, created_tasks=created_tasks, stats=stats)
