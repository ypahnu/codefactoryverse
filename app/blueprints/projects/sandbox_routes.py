from flask import Blueprint, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Team, Project, ProjectSandbox, ProjectActivity
import logging

logger = logging.getLogger(__name__)

def _wants_json():
    """Check if request wants JSON (fetch/XHR) or HTML page"""
    if request.is_json:
        return True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    # If Accept header prefers JSON over HTML
    accept = request.headers.get('Accept', '')
    if 'application/json' in accept and 'text/html' not in accept:
        return True
    # For our JS fetch calls to /sandbox/files and /sandbox/exec, they use application/json
    # For form POSTs (upload, start/stop), they want HTML redirect
    # Check if request is fetch from JS (has content-type application/json)
    if request.content_type and 'application/json' in request.content_type:
        return True
    return False

def _flash_and_redirect(message, category, team_slug, project_slug, task_id=None):
    """Helper to flash error and redirect to project view or task view"""
    flash(message, category)
    # Try to go back to task page if referrer has task
    ref = request.referrer or ''
    if task_id and f'/tasks/{task_id}' in ref:
        return redirect(url_for('tasks.view', team_slug=team_slug, project_slug=project_slug, task_id=task_id))
    if '/tasks/' in ref:
        import re
        m = re.search(r'/tasks/(\d+)', ref)
        if m:
            return redirect(url_for('tasks.view', team_slug=team_slug, project_slug=project_slug, task_id=m.group(1)))
    return redirect(url_for('projects.view', team_slug=team_slug, project_slug=project_slug))

sandbox_bp = Blueprint('project_sandbox', __name__)

@sandbox_bp.route('/team/<team_slug>/<project_slug>/sandbox/<action>', methods=['POST'])
@login_required
def sandbox_action(team_slug, project_slug, action):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()

    sandbox = ProjectSandbox.query.filter_by(project_id=project.id).first()
    if not sandbox and action != 'start':
        flash('No sandbox for this project. Create one with +Add Sandbox.', 'warning')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

    try:
        from app.services.modal_sandbox_service import create_project_sandbox_with_tunnel, check_tunnel_established, terminate_sandbox
        from datetime import datetime, timezone, timedelta

        if action == 'start':
            # If already exists and running, don't create new (enforce 1 per project for now)
            if sandbox and sandbox.is_alive():
                flash(f'Sandbox already running: {sandbox.name} - {sandbox.tunnel_url or "no tunnel yet"}', 'info')
                return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

            # Parse ports from form or use existing
            ports_str = request.form.get('ports') or ','.join(map(str, [sandbox.tunnel_port] if sandbox and sandbox.tunnel_port else [8000, 5173]))
            try:
                ports = [int(p.strip()) for p in ports_str.split(',') if p.strip().isdigit()]
                if not ports:
                    ports = [8000, 5173]
            except:
                ports = [8000, 5173]

            sandbox_type = request.form.get('sandbox_type', sandbox.type if sandbox else 'basic')

            # Create sandbox with tunnel (real or mock)
            result = create_project_sandbox_with_tunnel(
                project_id=project.id,
                project_slug=project.slug,
                team_slug=team.slug,
                sandbox_type=sandbox_type,
                ports=ports,
                timeout=86400
            )

            if not sandbox:
                # Create new DB entry if not exists
                sandbox = ProjectSandbox(
                    project_id=project.id,
                    name=result.get('sandbox_name', f"proj-{team.slug}-{project.slug}-{project.id}"),
                    type=sandbox_type,
                    runtime='gvisor',
                    status=result.get('status', 'Started'),
                    volume_name=f"codefactory-vol-{team.slug}-{project.slug}",
                    tunnel_enabled=True,
                    tunnel_port=ports[0],
                    tunnel_url=result.get('main_tunnel_url'),
                    tunnel_urls_json=str(result.get('tunnel_urls', {})).replace("'", '"'),
                    modal_sandbox_id=result.get('sandbox_id'),
                    last_heartbeat=datetime.now(timezone.utc),
                    last_started_at=datetime.now(timezone.utc),
                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=86400)
                )
                db.session.add(sandbox)
            else:
                sandbox.modal_sandbox_id = result.get('sandbox_id')
                sandbox.status = result.get('status', 'Started')
                sandbox.tunnel_url = result.get('main_tunnel_url')
                sandbox.tunnel_urls_json = str(result.get('tunnel_urls', {})).replace("'", '"')
                sandbox.last_heartbeat = datetime.now(timezone.utc)
                sandbox.last_started_at = datetime.now(timezone.utc)
                sandbox.expires_at = datetime.now(timezone.utc) + timedelta(seconds=86400)
                sandbox.tunnel_last_seen = datetime.now(timezone.utc)

            # Activity log: created HTTP with tunnel
            activity = ProjectActivity(
                project_id=project.id,
                user_id=current_user.id,
                type='sandbox_started' if action == 'start' else 'sandbox_restart',
                summary=f'created HTTP with tunnel: {result.get("main_tunnel_url")} (ports {ports}) - {result.get("sandbox_id")[:12]}',
                detail=result.get('request_log', '') + f"\n\nMain URL: {result.get('main_tunnel_url')}\nTLS: {result.get('main_tls_socket')}\nFrontend URL: {result.get('user_tunnel_url')}\n"
            )
            db.session.add(activity)
            db.session.commit()

            # Print like example
            print(f"\n🚀 Creating HTTP Server with tunnel!")
            print(f"🌐 Public URL: {result.get('main_tunnel_url')}")
            print(f"🔒 TLS Socket: {result.get('main_tls_socket')}")
            print(f"\n📡 Available endpoints:")
            print(f"  POST {result.get('main_tunnel_url')}/edit - Update display text")
            print(f"  GET  {result.get('main_tunnel_url')}/heartbeat - Health check")
            print(f"\n💡 You can now access these endpoints from anywhere on the internet!")
            print()
            if result.get('user_tunnel_url'):
                print(f"🌐 Frontend URL: {result.get('user_tunnel_url')} <-- Open this in your browser!")
                print(f"🔒 TLS Socket: {result.get('user_tunnel_tls_socket')}")
            print("Sandbox server with tunnel running")

            flash(f'🚀 Created HTTP with tunnel! Public URL: {result.get("main_tunnel_url")} - Frontend: {result.get("user_tunnel_url")} - Sandbox ID: {result.get("sandbox_id")[:12]}', 'success')

        elif action == 'stop':
            if sandbox and sandbox.modal_sandbox_id:
                result = terminate_sandbox(sandbox.modal_sandbox_id)
                sandbox.status = 'Finished'
                sandbox.last_stopped_at = datetime.now(timezone.utc)
                activity = ProjectActivity(
                    project_id=project.id,
                    user_id=current_user.id,
                    type='sandbox_stopped',
                    summary=f'Sandbox stopped: {sandbox.name} ({sandbox.modal_sandbox_id[:12] if sandbox.modal_sandbox_id else ""})',
                    detail=f"Terminated sandbox {sandbox.modal_sandbox_id}"
                )
                db.session.add(activity)
                db.session.commit()
                flash(f'Sandbox {sandbox.name} stopped', 'info')
            else:
                flash('No sandbox to stop', 'warning')

        elif action == 'restart':
            # Stop if running, then start again
            if sandbox and sandbox.modal_sandbox_id:
                terminate_sandbox(sandbox.modal_sandbox_id)
                sandbox.status = 'Finished'
                db.session.commit()
            # Now start new one
            return sandbox_action(team_slug, project_slug, 'start')

        elif action == 'check_tunnel':
            if sandbox and sandbox.modal_sandbox_id:
                result = check_tunnel_established(sandbox.modal_sandbox_id)
                if result.get('established'):
                    sandbox.tunnel_url = result.get('tunnel_url')
                    sandbox.status = 'Ready'
                    sandbox.tunnel_last_seen = datetime.now(timezone.utc)
                    sandbox.last_heartbeat = datetime.now(timezone.utc)
                    db.session.commit()
                    # Log success, don't show JSON page - flash and redirect per user request
                    logger.info(f"Tunnel check OK for {sandbox.modal_sandbox_id}: {result.get('tunnel_url')}")
                    if _wants_json():
                        return jsonify({"established": True, "tunnel_url": result.get('tunnel_url'), "message": result.get('message')})
                    flash(f'✅ Tunnel established: {result.get("tunnel_url")} - {result.get("message")}', 'success')
                else:
                    # If sandbox not found in Modal (deleted via dashboard), mark as finished
                    msg_lower = (result.get('message','') + ' ' + str(result.get('error',''))).lower()
                    if 'not found' in msg_lower or 'unavailable' in msg_lower or 'notfound' in msg_lower or '404' in msg_lower:
                        logger.warning(f"Sandbox {sandbox.modal_sandbox_id} not found in Modal (deleted via dashboard), marking as Finished")
                        sandbox.status = 'Finished'
                        sandbox.tunnel_url = None
                        sandbox.tunnel_urls_json = None
                        activity = ProjectActivity(
                            project_id=project.id,
                            user_id=current_user.id,
                            type='sandbox_deleted',
                            summary=f'Sandbox {sandbox.name} deleted in Modal dashboard (not found) - cleaned up',
                            detail=f"Check tunnel failed: {result.get('message')} - Sandbox ID {sandbox.modal_sandbox_id} not found at https://modal.com/containers/{team.slug}/main/sandboxes"
                        )
                        db.session.add(activity)
                        db.session.commit()
                        if _wants_json():
                            return jsonify({"established": False, "message": f"Sandbox deleted in Modal dashboard (not found). Cleaned up DB. Was: {result.get('message')}", "deleted": True})
                        flash(f'⚠️ Sandbox {sandbox.name} not found in Modal (deleted via dashboard at https://modal.com/containers/ypahnu/main/sandboxes). Cleaned up DB - shows no tunnel now.', 'warning')
                    else:
                        logger.warning(f"Tunnel not established for {sandbox.modal_sandbox_id}: {result.get('message')}")
                        if _wants_json():
                            return jsonify({"established": False, "message": result.get('message')})
                        flash(f'❌ Tunnel not established: {result.get("message")}', 'warning')
            else:
                logger.warning(f"Check tunnel called but no sandbox for project {project.id}")
                if _wants_json():
                    return jsonify({"established": False, "message": "No sandbox for this project. Create one with +Add Sandbox first."})
                flash('No sandbox for this project. Create one with +Add Sandbox first.', 'warning')

        else:
            flash(f'Unknown action {action}', 'danger')

    except Exception as e:
        logger.exception(f"Sandbox action {action} failed for project {project.id}: {e}")
        flash(f'Sandbox {action} failed: {e}', 'danger')

    # Redirect based on where request came from
    ref = request.referrer or ''
    if f'/tasks/' in ref:
        # If from task page, go back to task page to see activity in sidebar
        # Try to extract task_id from ref
        import re
        m = re.search(r'/tasks/(\d+)', ref)
        if m:
            task_id = m.group(1)
            return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task_id))
    return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

@sandbox_bp.route('/team/<team_slug>/<project_slug>/sandbox/status', methods=['GET'])
@login_required
def sandbox_status(team_slug, project_slug):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    sandbox = ProjectSandbox.query.filter_by(project_id=project.id).first()

    if not sandbox:
        return jsonify({"exists": False, "message": "No sandbox for this project"})

    return jsonify({
        "exists": True,
        "id": sandbox.id,
        "name": sandbox.name,
        "type": sandbox.type,
        "runtime": sandbox.runtime,
        "status": sandbox.status,
        "modal_sandbox_id": sandbox.modal_sandbox_id,
        "volume_name": sandbox.volume_name,
        "tunnel_enabled": sandbox.tunnel_enabled,
        "tunnel_port": sandbox.tunnel_port,
        "tunnel_url": sandbox.tunnel_url,
        "tunnel_urls": sandbox.tunnels(),
        "is_alive": sandbox.is_alive(),
        "created_at": sandbox.created_at.isoformat() if sandbox.created_at else None,
        "last_heartbeat": sandbox.last_heartbeat.isoformat() if sandbox.last_heartbeat else None,
        "expires_at": sandbox.expires_at.isoformat() if sandbox.expires_at else None,
        "git_repo_url": sandbox.git_repo_url,
        "dev_command": sandbox.dev_command,
    })

@sandbox_bp.route('/team/<team_slug>/<project_slug>/sandbox/activity', methods=['GET'])
@login_required
def sandbox_activity(team_slug, project_slug):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    activities = ProjectActivity.query.filter_by(project_id=project.id).order_by(ProjectActivity.created_at.desc()).limit(20).all()

    return jsonify([
        {
            "id": a.id,
            "type": a.type,
            "summary": a.summary,
            "task_id": a.task_id,
            "agent_id": a.agent_id,
            "created_at": a.created_at.isoformat() if a.created_at else None
        } for a in activities
    ])


# === FILE UPLOAD - Per-Project, No Volume Local (Filesystem API) ===

@sandbox_bp.route('/team/<team_slug>/<project_slug>/sandbox/upload', methods=['POST'])
@login_required
def sandbox_upload(team_slug, project_slug):
    """
    Upload file to sandbox per-project via filesystem API (no volume)
    FormData: file + remote_path (default /workspace/{filename})
    Uses sb.filesystem.copy_from_local per Modal docs https://modal.com/docs/guide/sandbox-files
    Now shows error message in page, not JSON, per user request - logs it
    """
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    sandbox = ProjectSandbox.query.filter_by(project_id=project.id).first()

    if not sandbox:
        logger.warning(f"Upload attempt but no sandbox for project {project.id} - user {current_user.username}")
        if _wants_json():
            return jsonify({"error": "No sandbox for this project. Create one with +Add Sandbox first."}), 404
        flash('No sandbox for this project. Create one with +Add Sandbox first.', 'danger')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

    # Allow mock upload even if modal_sandbox_id is None (old sandbox from before tunnel feature)
    # Use project id as fallback sandbox_id for mock mode
    sandbox_id = sandbox.modal_sandbox_id or f"sb-mock-{sandbox.name}-{project.id}"

    if 'file' not in request.files:
        logger.warning(f"Upload attempt but no file field - project {project.id}")
        if _wants_json():
            return jsonify({"error": "No file in request. Use field 'file'"}), 400
        flash('No file in request. Use field file', 'danger')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

    file = request.files['file']
    remote_path = request.form.get('remote_path', f"/workspace/{file.filename}")
    if not remote_path.startswith('/'):
        remote_path = f"/workspace/{remote_path.lstrip('/')}"

    # Save locally temp
    import os, tempfile, uuid
    tmp_dir = tempfile.gettempdir()
    local_tmp = os.path.join(tmp_dir, f"{uuid.uuid4()}_{file.filename}")
    file.save(local_tmp)

    try:
        from app.services.modal_sandbox_service import upload_file_to_sandbox
        result = upload_file_to_sandbox(sandbox_id, local_tmp, remote_path)

        # Log activity for cross-task visibility: file uploaded while chatting in other task will be visible
        activity = ProjectActivity(
            project_id=project.id,
            user_id=current_user.id,
            type='file_upload',
            summary=f'Uploaded {file.filename} to {remote_path} via filesystem API (no volume, per-project)',
            detail=f"File: {file.filename} ({os.path.getsize(local_tmp)} bytes)\nLocal tmp: {local_tmp}\nRemote: {remote_path}\nSandbox: {sandbox_id}\nRequest log:\n{result.get('request_log','')}"
        )
        db.session.add(activity)
        db.session.commit()

        # Cleanup tmp
        try:
            os.remove(local_tmp)
        except:
            pass

        if result.get('uploaded'):
            logger.info(f"File upload OK: {file.filename} to {remote_path} in sandbox {sandbox_id} - real: {not result.get('mock')}")
            if _wants_json():
                return jsonify({
                    "uploaded": True,
                    "filename": file.filename,
                    "remote_path": remote_path,
                    "sandbox_id": sandbox_id,
                    "project_id": project.id,
                    "message": f"Uploaded {file.filename} to {remote_path} - per-project, no volume, via filesystem API (real sandbox)",
                    "request_log": result.get('request_log', ''),
                    "mock": result.get('mock', False)
                })
            flash(f'✅ Uploaded {file.filename} to {remote_path} in real sandbox {sandbox.name} - per-project, no volume', 'success')
            return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))
        else:
            logger.error(f"File upload failed: {result.get('error')} for {file.filename} to {remote_path}")
            if _wants_json():
                return jsonify({"error": result.get('error', 'Upload failed'), "remote_path": remote_path}), 500
            flash(f'❌ Upload failed: {result.get("error", "Upload failed")} for {file.filename}', 'danger')
            return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

    except Exception as e:
        logger.exception(f"File upload to sandbox {sandbox_id} failed: {e}")
        if _wants_json():
            return jsonify({"error": str(e)}), 500
        flash(f'❌ Upload failed: {e} - logged', 'danger')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

@sandbox_bp.route('/team/<team_slug>/<project_slug>/sandbox/files', methods=['GET'])
@login_required
def sandbox_files(team_slug, project_slug):
    """
    List files in sandbox per-project path via filesystem API (no volume)
    Query param: path=/workspace (default)
    Per-project: files are under /workspace (shared across tasks in same project)
    Returns JSON for JS fetch, but logs errors instead of JSON page for form cases
    """
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    sandbox = ProjectSandbox.query.filter_by(project_id=project.id).first()

    if not sandbox:
        logger.warning(f"List files: no sandbox for project {project.id}")
        if _wants_json():
            return jsonify({"error": "No sandbox for this project. Create one with +Add Sandbox first.", "files": []}), 404
        flash('No sandbox for this project. Create one with +Add Sandbox first.', 'warning')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

    sandbox_id = sandbox.modal_sandbox_id or f"sb-mock-{sandbox.name}-{project.id}"
    path = request.args.get('path', '/workspace')

    try:
        from app.services.modal_sandbox_service import list_files_in_sandbox
        result = list_files_in_sandbox(sandbox_id, path)
        # If sandbox was deleted in Modal dashboard, list will fail or return mock with message
        # Check and log
        if not result.get('files') and 'not found' in str(result.get('error','')).lower():
            logger.warning(f"Files list: sandbox {sandbox_id} not found in Modal (deleted via dashboard)")
        return jsonify(result)
    except Exception as e:
        logger.exception(f"List files failed for project {project.id} sandbox {sandbox_id}: {e}")
        if _wants_json():
            return jsonify({"error": str(e), "files": []}), 500
        flash(f'Failed to list files: {e} - logged', 'danger')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

@sandbox_bp.route('/team/<team_slug>/<project_slug>/sandbox/exec', methods=['POST'])
@login_required
def sandbox_exec(team_slug, project_slug):
    """
    Exec command in sandbox (for git clone, ls, etc.)
    Body JSON: {command: "git clone https://... /workspace/repo"}
    Uses sb.exec per Modal docs, per-project path
    """
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    sandbox = ProjectSandbox.query.filter_by(project_id=project.id).first()

    if not sandbox:
        logger.warning(f"Exec: no sandbox for project {project.id}")
        if _wants_json():
            return jsonify({"error": "No sandbox for this project"}), 404
        flash('No sandbox for this project', 'warning')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

    sandbox_id = sandbox.modal_sandbox_id or f"sb-mock-{sandbox.name}-{project.id}"

    data = request.get_json() or {}
    command = data.get('command') or request.form.get('command')
    if not command:
        return jsonify({"error": "command required"}), 400

    try:
        import modal
        from datetime import datetime, timezone

        # Real Modal only - no mock per user request per user
        # Check if sandbox_id is still mock/error from old DB - if so, tell user to recreate
        if sandbox_id.startswith("sb-mock-") or sandbox_id.startswith("sb-error-") or not sandbox_id.startswith("sb-"):
            logger.warning(f"Exec called but sandbox_id is mock/error/None: {sandbox_id} - real sandbox needed")
            if _wants_json():
                return jsonify({"error": f"Sandbox {sandbox_id} is mock/error, not real. Please recreate sandbox via +Add Sandbox or Restart. Real sandbox required for exec.", "sandbox_id": sandbox_id, "mock": True}), 400
            flash(f'Sandbox {sandbox.name} is mock/error ({sandbox_id[:20]}...), not real. Please recreate via Restart to get real Modal sandbox with tunnel.', 'warning')
            return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

        sb = modal.Sandbox.from_id(sandbox_id)
        # Simple bash -c exec - per-project path, real Modal
        p = sb.exec("bash", "-c", command)
        stdout = p.stdout.read()
        returncode = p.wait()

        logger.info(f"Exec in sandbox {sandbox_id}: {command} -> {returncode}")

        # Log activity if git-related
        if 'git' in command.lower():
            activity = ProjectActivity(
                project_id=project.id,
                user_id=current_user.id,
                type='git_pull' if 'pull' in command else 'git_clone',
                summary=f"Executed: {command[:100]} in sandbox {sandbox.name} per-project",
                detail=f"Command: {command}\nStdout: {stdout[:1000]}\nReturncode: {returncode}\nPer-project path: /workspace"
            )
            db.session.add(activity)
            db.session.commit()

        if _wants_json():
            return jsonify({
                "command": command,
                "stdout": stdout,
                "returncode": returncode,
                "sandbox_id": sandbox_id,
                "per_project": True
            })
        flash(f'Executed: {command[:80]} -> returncode {returncode} (real sandbox)', 'success')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

    except Exception as e:
        logger.exception(f"Exec in sandbox {sandbox_id} failed: {e}")
        if _wants_json():
            return jsonify({"error": str(e)}), 500
        flash(f'Exec failed: {e} - logged', 'danger')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

@sandbox_bp.route('/team/<team_slug>/<project_slug>/sandbox/clone-repo', methods=['POST'])
@login_required
def sandbox_clone_repo(team_slug, project_slug):
    """
    Git repo handling: do as we want
    Auto-clone if git_repo_url set in ProjectSandbox, or manual via form
    Per-project: clones into /workspace/repo
    """
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    sandbox = ProjectSandbox.query.filter_by(project_id=project.id).first()

    if not sandbox:
        logger.warning(f"Clone repo: no sandbox for project {project.id}")
        if _wants_json():
            return jsonify({"error": "No sandbox for this project. Create one with +Add Sandbox first."}), 404
        flash('No sandbox for this project. Create one with +Add Sandbox first.', 'warning')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

    sandbox_id = sandbox.modal_sandbox_id or f"sb-mock-{sandbox.name}-{project.id}"

    repo_url = request.form.get('repo_url') or (request.json.get('repo_url') if request.is_json else None)
    repo_url = repo_url or sandbox.git_repo_url
    branch = request.form.get('branch') or (request.json.get('branch') if request.is_json else None) or sandbox.git_branch or 'main'

    if not repo_url:
        logger.warning(f"Clone repo: no repo_url for project {project.id}")
        if _wants_json():
            return jsonify({"error": "git_repo_url required. Set in project sandbox config or provide repo_url param"}), 400
        flash('git_repo_url required. Set in project sandbox config or provide repo_url', 'danger')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

    try:
        from app.services.modal_sandbox_service import clone_repo_in_sandbox
        result = clone_repo_in_sandbox(sandbox_id, repo_url, branch, target_dir="/workspace/repo")

        # Update sandbox record with repo url if provided
        if repo_url and repo_url != sandbox.git_repo_url:
            sandbox.git_repo_url = repo_url
            sandbox.git_branch = branch
            db.session.commit()

        # Log activity for cross-task visibility
        activity = ProjectActivity(
            project_id=project.id,
            user_id=current_user.id,
            type='git_clone',
            summary=f"Cloned repo {repo_url} branch {branch} to /workspace/repo in sandbox {sandbox.name}",
            detail=f"Repo: {repo_url}\nBranch: {branch}\nResult: {result.get('output','')[:1000]}\nReturncode: {result.get('returncode')}\nRequest log: {result.get('request_log','')[:1000]}"
        )
        db.session.add(activity)
        db.session.commit()

        logger.info(f"Cloned repo {repo_url} to /workspace/repo in sandbox {sandbox_id}")

        if _wants_json():
            return jsonify(result)
        flash(f'Cloned repo {repo_url} branch {branch} to /workspace/repo in sandbox {sandbox.name} (real: {not result.get("mock")})', 'success')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

    except Exception as e:
        logger.exception(f"Clone repo failed for project {project.id}: {e}")
        if _wants_json():
            return jsonify({"error": str(e)}), 500
        flash(f'Clone repo failed: {e} - logged', 'danger')
        return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))
