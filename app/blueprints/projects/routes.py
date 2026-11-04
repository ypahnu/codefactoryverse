from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Team, Project, Task, ProjectSandbox, ProjectActivity
import re
import logging

logger = logging.getLogger(__name__)

projects_bp = Blueprint('projects', __name__)

def slugify(text):
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')

@projects_bp.route('/team/<team_slug>/create', methods=['GET', 'POST'])
@login_required
def create(team_slug):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        color = request.form.get('color', '#8b5cf6')
        if not name:
            flash('Project name required', 'danger')
            return redirect(url_for('projects.create', team_slug=team_slug))
        slug_base = slugify(name)
        slug = slug_base
        counter = 1
        while Project.query.filter_by(team_id=team.id, slug=slug).first():
            slug = f"{slug_base}-{counter}"
            counter += 1
        project = Project(name=name, slug=slug, description=description, team_id=team.id, owner_id=current_user.id, color=color)
        db.session.add(project)
        db.session.flush()  # Need ID for sandbox

        # Handle +Add Sandbox option
        add_sandbox = request.form.get('add_sandbox')
        sandbox_info_msg = ""
        if add_sandbox:
            try:
                sandbox_type = request.form.get('sandbox_type', 'basic')
                sandbox_runtime = request.form.get('sandbox_runtime', 'gvisor')
                sandbox_ports_str = request.form.get('sandbox_ports', '8000,5173')
                git_repo_url = request.form.get('git_repo_url', '').strip() or None
                dev_command = request.form.get('dev_command', '').strip() or None

                # Parse ports
                try:
                    ports = [int(p.strip()) for p in sandbox_ports_str.split(',') if p.strip().isdigit() or p.strip().lstrip('-').isdigit()]
                    # Handle non-digit check better
                    ports = []
                    for p in sandbox_ports_str.split(','):
                        p = p.strip()
                        if p.isdigit():
                            ports.append(int(p))
                    if not ports:
                        ports = [8000, 5173]
                except:
                    ports = [8000, 5173]

                # Create ProjectSandbox DB entry
                sandbox_name = f"proj-{team.slug}-{slug}-{project.id}"
                volume_name = f"codefactory-vol-{team.slug}-{slug}"

                sandbox = ProjectSandbox(
                    project_id=project.id,
                    name=sandbox_name,
                    display_name=f"{name} Workspace",
                    type=sandbox_type,
                    runtime=sandbox_runtime,
                    status='Creating',
                    volume_name=volume_name,
                    tunnel_enabled=True,
                    tunnel_port=ports[0] if ports else 8000,
                    git_repo_url=git_repo_url,
                    dev_command=dev_command,
                    image='codefactory-runtime'
                )
                db.session.add(sandbox)
                db.session.flush()

                # Try to create real Modal sandbox with tunnel (based on modal-vibe example)
                try:
                    from app.services.modal_sandbox_service import create_project_sandbox_with_tunnel
                    result = create_project_sandbox_with_tunnel(
                        project_id=project.id,
                        project_slug=slug,
                        team_slug=team.slug,
                        sandbox_type=sandbox_type,
                        ports=ports,
                        timeout=86400
                    )

                    # Update sandbox with result - tunnel check
                    sandbox.modal_sandbox_id = result.get('sandbox_id')
                    sandbox.status = result.get('status', 'Started')
                    sandbox.tunnel_url = result.get('main_tunnel_url')
                    sandbox.tunnel_urls_json = str(result.get('tunnel_urls', {})).replace("'", '"')
                    sandbox.tunnel_last_seen = db.func.now()
                    from datetime import datetime, timezone, timedelta
                    sandbox.last_heartbeat = datetime.now(timezone.utc)
                    sandbox.last_started_at = datetime.now(timezone.utc)
                    sandbox.expires_at = datetime.now(timezone.utc) + timedelta(seconds=86400)

                    # Create activity log: created HTTP with tunnel
                    tunnel_url = result.get('main_tunnel_url', 'unknown')
                    user_tunnel_url = result.get('user_tunnel_url', '')

                    # Log like example
                    log_detail = f"""🚀 Creating HTTP Server with tunnel!
🌐 Public URL: {result.get('main_tunnel_url')}
🔒 TLS Socket: {result.get('main_tls_socket')}

📡 Available endpoints:
  POST {result.get('main_tunnel_url')}/edit - Update display text
  GET  {result.get('main_tunnel_url')}/heartbeat - Health check

💡 You can now access these endpoints from anywhere on the internet!

🌐 Frontend URL: {user_tunnel_url} <-- Open this in your browser!
🔒 TLS Socket: {result.get('user_tls_socket')}

Sandbox server with tunnel running

Request log:
{result.get('request_log','')}

Source: {'mock' if result.get('mock') else 'modal'} - Ports: {ports}
"""

                    activity = ProjectActivity(
                        project_id=project.id,
                        user_id=current_user.id,
                        type='sandbox_created',
                        summary=f'created HTTP with tunnel: {tunnel_url} (ports {ports})',
                        detail=log_detail
                    )
                    db.session.add(activity)

                    sandbox_info_msg = f" + Sandbox created! Public URL: {tunnel_url} (Frontend: {user_tunnel_url}) - created HTTP with tunnel"

                    print(f"\n🚀 Creating HTTP Server with tunnel!")
                    print(f"🌐 Public URL: {result.get('main_tunnel_url')}")
                    print(f"🔒 TLS Socket: {result.get('main_tls_socket')}")
                    print(f"\n📡 Available endpoints:")
                    print(f"  POST {result.get('main_tunnel_url')}/edit - Update display text")
                    print(f"  GET  {result.get('main_tunnel_url')}/heartbeat - Health check")
                    print(f"\n💡 You can now access these endpoints from anywhere on the internet!")
                    print()
                    if user_tunnel_url:
                        print(f"🌐 Frontend URL: {user_tunnel_url} <-- Open this in your browser!")
                        print(f"🔒 TLS Socket: {result.get('user_tls_socket')}")
                    print("\nSandbox server with tunnel running")

                except Exception as e:
                    logger.exception(f"Failed to create Modal sandbox for project {project.id}: {e}")
                    sandbox.status = 'Error'
                    # Still keep DB entry but with error
                    activity = ProjectActivity(
                        project_id=project.id,
                        user_id=current_user.id,
                        type='sandbox_error',
                        summary=f'Sandbox creation failed: {str(e)[:100]}',
                        detail=str(e)
                    )
                    db.session.add(activity)
                    sandbox_info_msg = f" + Sandbox DB created but Modal creation failed (mock used): {e}"

            except Exception as e:
                logger.exception(f"Failed to handle +Add Sandbox: {e}")
                sandbox_info_msg = f" (Sandbox option failed: {e})"

        db.session.commit()
        flash(f'Project {name} created!{sandbox_info_msg}', 'success')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))
    return render_template('projects/create.html', team=team)

@projects_bp.route('/team/<team_slug>/<project_slug>')
@login_required
def view(team_slug, project_slug):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    stats = project.task_stats()
    tasks_todo = project.tasks.filter_by(status='todo').order_by(Task.position).all()
    tasks_in_progress = project.tasks.filter_by(status='in_progress').order_by(Task.position).all()
    tasks_done = project.tasks.filter_by(status='done').order_by(Task.position).all()
    # Sandbox info for this project (1 per project for now, but design supports multiples)
    # Gate: tabs + "Started - alive" render ONLY when this request's tunnel check
    # establishes (sandbox_live). Otherwise the DB status is corrected and the
    # page shows recreate / create-sandbox instead.
    sandbox_live = False
    try:
        from app.models import ProjectSandbox, ProjectActivity
        project_sandbox = ProjectSandbox.query.filter_by(project_id=project.id).first()
        project_sandboxes = ProjectSandbox.query.filter_by(project_id=project.id).all()
        recent_activities = ProjectActivity.query.filter_by(project_id=project.id).order_by(ProjectActivity.created_at.desc()).limit(10).all()

        # If sandbox exists in DB, verify tunnels before showing it as alive.
        if project_sandbox and project_sandbox.modal_sandbox_id:
            try:
                from app.services.modal_sandbox_service import check_tunnel_established
                if project_sandbox.status in ['Started', 'Ready', 'Creating', 'Scheduled', 'Error', 'Running']:
                    result = check_tunnel_established(project_sandbox.modal_sandbox_id)
                    msg_lower = (result.get('message','') + ' ' + str(result.get('error',''))).lower()
                    not_found = any(x in msg_lower for x in ['not found', 'unavailable', 'notfound', 'is not a valid sandbox id', '404'])
                    # Our own network down (not Modal's answer): never mutate DB on that.
                    connection_down = 'could not connect' in msg_lower
                    if result.get('established'):
                        # Tunnel verified this request: alive. Refresh heartbeat.
                        from datetime import datetime, timezone
                        project_sandbox.last_heartbeat = datetime.now(timezone.utc)
                        project_sandbox.tunnel_last_seen = datetime.now(timezone.utc)
                        # If tunnel_url changed (maybe new URL after restart), update
                        if result.get('tunnel_url') and result.get('tunnel_url') != project_sandbox.tunnel_url:
                            project_sandbox.tunnel_url = result.get('tunnel_url')
                        # Promote transitional / recovered states
                        if project_sandbox.status in ['Creating', 'Scheduled']:
                            project_sandbox.status = 'Started'
                        elif project_sandbox.status in ['Error', 'Finished']:
                            project_sandbox.status = 'Ready'
                        db.session.commit()
                        sandbox_live = True
                    elif not connection_down and (not_found or project_sandbox.status in ['Started', 'Ready', 'Running', 'Error']):
                        # Exists in DB but tunnel check established == false:
                        # correct the DB status and show recreate instead of tabs.
                        project_sandbox.status = 'Finished'
                        project_sandbox.tunnel_url = None
                        project_sandbox.tunnel_urls_json = None
                        # Log activity
                        activity = ProjectActivity(
                            project_id=project.id,
                            user_id=current_user.id,
                            type='sandbox_unreachable',
                            summary=f'Sandbox {project_sandbox.name} tunnel check failed (established=false) - marked Finished, recreate to get a fresh tunnel',
                            detail=f"Tunnel check failed: {result.get('message')} - Sandbox ID {project_sandbox.modal_sandbox_id} - marked as Finished"
                        )
                        db.session.add(activity)
                        db.session.commit()
                    # Creating/Scheduled without not_found: still starting, leave alone.
            except Exception as e:
                # Don't fail page load if Modal check fails, just log
                import logging
                logging.getLogger(__name__).warning(f"Failed to sync sandbox status from Modal for {project_sandbox.modal_sandbox_id}: {e}")

    except Exception as e:
        project_sandbox = None
        project_sandboxes = []
        recent_activities = []
    return render_template('projects/view.html', team=team, project=project, stats=stats, tasks_todo=tasks_todo, tasks_in_progress=tasks_in_progress, tasks_done=tasks_done, project_sandbox=project_sandbox, project_sandboxes=project_sandboxes, recent_activities=recent_activities, sandbox_live=sandbox_live)

@projects_bp.route('/team/<team_slug>/<project_slug>/edit', methods=['GET', 'POST'])
@login_required
def edit(team_slug, project_slug):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    if request.method == 'POST':
        project.name = request.form.get('name', '').strip() or project.name
        project.description = request.form.get('description', '')
        project.color = request.form.get('color', project.color)
        db.session.commit()
        flash('Project updated', 'success')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))
    return render_template('projects/edit.html', team=team, project=project)

@projects_bp.route('/team/<team_slug>/<project_slug>/delete', methods=['POST'])
@login_required
def delete(team_slug, project_slug):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    if project.owner_id != current_user.id and team.owner_id != current_user.id:
        flash('Not authorized', 'danger')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))
    db.session.delete(project)
    db.session.commit()
    flash('Project deleted', 'info')
    return redirect(url_for('teams.view', slug=team.slug))
