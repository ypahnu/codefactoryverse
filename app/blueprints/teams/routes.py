from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Team, User, Project
import re

teams_bp = Blueprint('teams', __name__)

def slugify(text):
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')

@teams_bp.route('/')
@login_required
def index():
    teams = current_user.teams.all()
    owned = Team.query.filter_by(owner_id=current_user.id).all()
    # merge unique
    all_teams = {t.id: t for t in teams + owned}
    return render_template('teams/index.html', teams=list(all_teams.values()))

@teams_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        color = request.form.get('color', '#6366f1')
        if not name:
            flash('Team name required', 'danger')
            return redirect(url_for('teams.create'))
        slug_base = slugify(name)
        slug = slug_base
        counter = 1
        while Team.query.filter_by(slug=slug).first():
            slug = f"{slug_base}-{counter}"
            counter += 1
        team = Team(name=name, slug=slug, description=description, owner_id=current_user.id, avatar_color=color)
        db.session.add(team)
        db.session.flush()
        team.members.append(current_user)
        db.session.commit()
        flash(f'Team {name} created!', 'success')
        return redirect(url_for('teams.view', slug=team.slug))
    return render_template('teams/create.html')

@teams_bp.route('/<slug>')
@login_required
def view(slug):
    team = Team.query.filter_by(slug=slug).first_or_404()
    # check membership
    is_member = team.members.filter_by(id=current_user.id).first() is not None or team.owner_id == current_user.id
    if not is_member:
        flash('You are not a member of this team', 'warning')
        return redirect(url_for('teams.index'))
    projects = team.projects.order_by(Project.updated_at.desc()).all()
    members = team.members.all()
    total_tasks = sum([p.tasks.count() for p in projects])
    return render_template('teams/view.html', team=team, projects=projects, members=members, is_owner=team.owner_id==current_user.id, total_tasks=total_tasks)

@teams_bp.route('/<slug>/invite', methods=['POST'])
@login_required
def invite(slug):
    team = Team.query.filter_by(slug=slug).first_or_404()
    if team.owner_id != current_user.id:
        flash('Only owner can invite', 'danger')
        return redirect(url_for('teams.view', slug=slug))
    username = request.form.get('username', '').strip()
    user = User.query.filter_by(username=username).first()
    if not user:
        user = User.query.filter_by(email=username).first()
    if not user:
        flash('User not found', 'danger')
        return redirect(url_for('teams.view', slug=slug))
    if team.members.filter_by(id=user.id).first():
        flash('User already member', 'info')
        return redirect(url_for('teams.view', slug=slug))
    team.members.append(user)
    db.session.commit()
    flash(f'{user.username} added to team', 'success')
    return redirect(url_for('teams.view', slug=slug))

@teams_bp.route('/<slug>/delete', methods=['POST'])
@login_required
def delete(slug):
    team = Team.query.filter_by(slug=slug).first_or_404()
    if team.owner_id != current_user.id:
        flash('Only owner can delete', 'danger')
        return redirect(url_for('teams.view', slug=slug))
    db.session.delete(team)
    db.session.commit()
    flash('Team deleted', 'info')
    return redirect(url_for('teams.index'))
