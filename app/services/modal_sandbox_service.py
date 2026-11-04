"""
Modal Sandbox Service - Async Only, Real Modal Only
Based on https://github.com/modal-labs/modal-vibe/blob/main/sandbox/start_sandbox.py

- No mock mode, everything is Modal (real)
- Async only, no sync wrapper
- Uses Filesystem API per https://modal.com/docs/guide/sandbox-files (no Volume)

Usage:
  from app.services.modal_sandbox_service import create_project_sandbox_with_tunnel
  result = create_project_sandbox_with_tunnel(...)  # sync wrapper for Flask routes
  Or await create_project_sandbox_with_tunnel_async(...) from async code.
  Low-level create_sandbox_with_tunnel_async(app, image, ...) is the generic
  builder; create_project_sandbox_with_tunnel_async(...) is the project
  entrypoint that computes sandbox_name and delegates to it. Keep both.
"""

import os
import json
import logging
from typing import Dict, List
import modal

logger = logging.getLogger(__name__)

SANDBOX_TIMEOUT = 86400  # 24 hours as in modal-vibe example

def _run_sync(coro_factory):
    """Run an async factory in Flask sync context (single helper, no duplication)."""
    import asyncio
    try:
        return asyncio.run(coro_factory())
    except RuntimeError:
        # Already inside a running loop - use a fresh loop
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro_factory())
        finally:
            loop.close()

def get_default_image():
    """Default image with startup.sh that keeps sandbox alive for file ops"""
    return (
        modal.Image.debian_slim()
        .pip_install("fastapi[standard]")
        .apt_install("curl", "git")
        .env({"PYTHONUNBUFFERED": "1"})
        .run_commands(
            "mkdir -p /workspace",
            "echo '#!/bin/bash' > /root/startup.sh",
            "echo 'echo Workspace ready at /workspace - per-project, filesystem API, no volume' >> /root/startup.sh",
            "echo 'while true; do sleep 1; done' >> /root/startup.sh",
            "chmod +x /root/startup.sh",
            "echo 'Workspace ready at /workspace - per-project, filesystem API' > /workspace/README.md"
        )
    )

def _get_modal_app(app_name: str = "codefactory-platform"):
    return modal.App.lookup(app_name, create_if_missing=True)

async def create_sandbox_with_tunnel_async(app: modal.App, 
                                           image: modal.Image, 
                                           ports: List[int] = None,
                                           sandbox_name: str = None,
                                           team_slug: str = None,
                                           project_slug: str = None,
                                           project_id: int = None,
                                           timeout: int = SANDBOX_TIMEOUT):
    """
    Create sandbox with HTTP tunnel - async only, real Modal only
    Based on modal-vibe example, with name, tags, cpu, memory for dashboard visibility
    """
    if ports is None:
        ports = [8000, 5173]

    print("🚀 Creating sandbox...")
    create_kwargs = {
        "image": image,
        "app": app,
        "timeout": timeout,
        "encrypted_ports": ports,
    }
    if sandbox_name:
        create_kwargs["name"] = sandbox_name  # Enforces 1 per project, raises AlreadyExistsError if exists (the proj-6 case)
    if team_slug and project_slug:
        create_kwargs["tags"] = {
            "team": team_slug, 
            "project": project_slug, 
            "project_id": str(project_id) if project_id else "unknown"
        }
    create_kwargs["cpu"] = 0.5
    create_kwargs["memory"] = 512

    try:
        sb = await modal.Sandbox.create.aio(
            "/bin/bash",
            "/root/startup.sh",
            **create_kwargs
        )
    except modal.exception.AlreadyExistsError as e:
        # Sandbox name already exists and is running on Modal dashboard
        # This is exactly the proj-6 case: proj-acme-corp-proj-6-8 still running but DB was overwritten with sb-error
        # Instead of generating sb-error-... and orphaning real sandbox, fetch existing
        print(f"⚠️ Sandbox name {sandbox_name} already exists (AlreadyExistsError) - fetching existing real sandbox instead of failing")
        logger.warning(f"Sandbox {sandbox_name} already exists, fetching existing: {e}")
        try:
            # Try from_name (only works if running)
            sb = await modal.Sandbox.from_name.aio(sandbox_name, app=app)
            print(f"♻️ Found existing sandbox by name: {sb.object_id} - reusing, not overwriting DB with sb-error")
        except Exception as fetch_e:
            logger.warning(f"Failed to fetch existing sandbox by name {sandbox_name}: {fetch_e}, trying list by tags")
            # Fallback: list sandboxes with tag project_id
            try:
                found = None
                async for candidate in modal.Sandbox.list.aio(app_id=app.app_id, tags={"project_id": str(project_id)} if project_id else {}):
                    # Check name matches or tags match
                    if getattr(candidate, 'name', None) == sandbox_name or (team_slug and project_slug and team_slug in str(getattr(candidate, 'tags', {}))):
                        found = candidate
                        break
                if found:
                    sb = found
                    print(f"♻️ Found existing sandbox via list: {sb.object_id}")
                else:
                    # If still not found, re-raise original AlreadyExistsError with clear message, don't generate sb-error that overwrites DB
                    raise Exception(f"Sandbox name {sandbox_name} already exists and is running on Modal dashboard at https://modal.com/containers/ypahnu/main/sandboxes or codefactory-platform, but could not be fetched. Please stop it via dashboard or wait. Original error: {e}") from e
            except Exception as list_e:
                raise Exception(f"Sandbox {sandbox_name} already exists (running on Modal) but fetch failed: {list_e}. Original: {e}") from e
    print(f"📋 Created sandbox with ID: {sb.object_id}")

    print("⏳ Waiting for tunnels to establish...")
    tunnels = await sb.tunnels.aio()

    main_port = ports[0]
    user_port = ports[1] if len(ports) > 1 else None
    main_tunnel = tunnels.get(main_port)
    user_tunnel = tunnels.get(user_port) if user_port else None

    if main_tunnel:
        print("\n🚀 Creating HTTP Server with tunnel!")
        print(f"🌐 Public URL: {main_tunnel.url}")
        print(f"🔒 TLS Socket: {main_tunnel.tls_socket}")
        print("\n📡 Available endpoints:")
        print(f"  POST {main_tunnel.url}/edit - Update display text")
        print(f"  GET  {main_tunnel.url}/heartbeat - Health check")
        print("\n💡 You can now access these endpoints from anywhere on the internet!")
        print()

    if user_tunnel:
        print(f"🌐 Frontend URL: {user_tunnel.url} <-- Open this in your browser!")
        print(f"🔒 TLS Socket: {user_tunnel.tls_socket}")

    print("Sandbox server with tunnel running")

    tunnel_urls = {}
    for port, tunnel in tunnels.items():
        tunnel_urls[str(port)] = {
            "url": tunnel.url,
            "tls_socket": tunnel.tls_socket
        }

    return {
        "sandbox_id": sb.object_id,
        "main_tunnel_url": main_tunnel.url if main_tunnel else None,
        "main_tls_socket": main_tunnel.tls_socket if main_tunnel else None,
        "user_tunnel_url": user_tunnel.url if user_tunnel else None,
        "user_tls_socket": user_tunnel.tls_socket if user_tunnel else None,
        "tunnel_urls": tunnel_urls,
        "ports": ports,
        "status": "Started"
    }

async def create_project_sandbox_with_tunnel_async(project_id: int,
                                                   project_slug: str,
                                                   team_slug: str,
                                                   sandbox_type: str = "basic",
                                                   ports: List[int] = None,
                                                   timeout: int = SANDBOX_TIMEOUT):
    """Async entrypoint - creates sandbox for project with tunnel"""
    if ports is None:
        ports = [8000, 5173]

    sandbox_name = f"proj-{team_slug}-{project_slug}-{project_id}"
    app = _get_modal_app("codefactory-platform")
    image = get_default_image()

    print(f"\n🔧 Creating sandbox for project {project_slug} (ID {project_id})")
    print(f"   Team: {team_slug}")
    print(f"   Name: {sandbox_name}")
    print(f"   Type: {sandbox_type}")
    print(f"   Ports: {ports}")

    result = await create_sandbox_with_tunnel_async(
        app=app,
        image=image,
        ports=ports,
        sandbox_name=sandbox_name,
        team_slug=team_slug,
        project_slug=project_slug,
        project_id=project_id,
        timeout=timeout
    )

    # Build request log as code
    main_port = ports[0] if ports else 8000
    has_second = len(ports) > 1
    request_log_code = f"""# REQUEST LOG - Create Sandbox with Tunnel (modal-vibe example)
# https://github.com/modal-labs/modal-vibe/blob/main/sandbox/start_sandbox.py
# Project: {project_slug} (ID {project_id}) Team: {team_slug}
# Per-project, no volume, filesystem API

import modal

SANDBOX_TIMEOUT = {timeout}

async def run_sandbox_server_with_tunnel(app, image):
    sb = await modal.Sandbox.create.aio(
        "/bin/bash", "/root/startup.sh",
        image=image, app=app, timeout={timeout},
        encrypted_ports={ports},
        name="{sandbox_name}",
        tags={{"team": "{team_slug}", "project": "{project_slug}", "project_id": "{project_id}"}},
        cpu=0.5, memory=512
    )
    tunnels = await sb.tunnels.aio()
    main_tunnel = tunnels[{main_port}]
    print(f"Public URL: {{main_tunnel.url}}")
    return sb.object_id, main_tunnel.url
"""

    print(request_log_code)

    result["request_log"] = request_log_code
    result["project_id"] = project_id
    result["project_slug"] = project_slug
    result["team_slug"] = team_slug
    result["sandbox_name"] = sandbox_name
    result["sandbox_type"] = sandbox_type

    return result

# Sync wrapper for Flask (sync routes call async Modal via _run_sync)
def create_project_sandbox_with_tunnel(project_id: int, project_slug: str, team_slug: str, sandbox_type: str = "basic", ports: List[int] = None, timeout: int = SANDBOX_TIMEOUT) -> Dict:
    """Sync wrapper for Flask routes - runs async Modal."""
    return _run_sync(lambda: create_project_sandbox_with_tunnel_async(
        project_id=project_id,
        project_slug=project_slug,
        team_slug=team_slug,
        sandbox_type=sandbox_type,
        ports=ports,
        timeout=timeout
    ))

async def check_tunnel_established_async(sandbox_id: str) -> Dict:
    """Async check if tunnel is established"""
    try:
        sb = await modal.Sandbox.from_id.aio(sandbox_id)
        tunnels = await sb.tunnels.aio()
        if tunnels:
            main_tunnel = list(tunnels.values())[0]
            return {
                "established": True,
                "message": f"created HTTP with tunnel: {main_tunnel.url}",
                "tunnel_url": main_tunnel.url,
                "tls_socket": main_tunnel.tls_socket,
                "all_tunnels": {str(port): {"url": t.url, "tls_socket": t.tls_socket} for port, t in tunnels.items()},
                "status": "Started"
            }
        else:
            return {"established": False, "message": "Waiting for tunnel to establish...", "status": "Scheduled"}
    except Exception as e:
        logger.warning(f"Tunnel check failed for {sandbox_id}: {e}")
        return {"established": False, "message": f"Tunnel check failed: {e}", "status": "Error", "error": str(e)}

def check_tunnel_established(sandbox_id: str) -> Dict:
    return _run_sync(lambda: check_tunnel_established_async(sandbox_id))

async def terminate_sandbox_async(sandbox_id: str) -> Dict:
    sb = await modal.Sandbox.from_id.aio(sandbox_id)
    await sb.terminate.aio()
    print(f"Terminated sandbox {sandbox_id}")
    return {"terminated": True, "sandbox_id": sandbox_id}

def terminate_sandbox(sandbox_id: str) -> Dict:
    return _run_sync(lambda: terminate_sandbox_async(sandbox_id))

# === FILE TRANSFER - Per-Project, No Volume, Filesystem API Only (Async) ===
# Based on https://modal.com/docs/guide/sandbox-files
# No mock, everything is Modal (real)

async def upload_file_to_sandbox_async(sandbox_id: str, local_path: str, remote_path: str) -> Dict:
    """Send file to sandbox via filesystem API (no volume), per-project"""
    sb = await modal.Sandbox.from_id.aio(sandbox_id)
    await sb.filesystem.copy_from_local.aio(local_path, remote_path)
    print(f"Uploaded {local_path} to sandbox {sandbox_id} at {remote_path} via filesystem API (no volume)")

    request_log = f"""# Send File to Sandbox (Filesystem API, No Volume, Per-Project)
# https://modal.com/docs/guide/sandbox-files
# Sandbox ID: {sandbox_id}
# Local: {local_path} -> Remote: {remote_path} (per-project path under /workspace)

import modal
sb = await modal.Sandbox.from_id.aio("{sandbox_id}")
await sb.filesystem.copy_from_local.aio("{local_path}", "{remote_path}")
"""

    return {
        "uploaded": True,
        "sandbox_id": sandbox_id,
        "local_path": local_path,
        "remote_path": remote_path,
        "request_log": request_log,
        "message": f"Uploaded {local_path} to {remote_path} via filesystem API - per-project, no volume"
    }

def upload_file_to_sandbox(sandbox_id: str, local_path: str, remote_path: str) -> Dict:
    return _run_sync(lambda: upload_file_to_sandbox_async(sandbox_id, local_path, remote_path))

async def write_text_to_sandbox_async(sandbox_id: str, content: str, remote_path: str) -> Dict:
    """Write text directly to sandbox file via filesystem API (no mock) - creates new files if don't exist, strips file marker already done, corrects typo worksapce->workspace"""
    # Correct typo worksapce, worspace, workpace, workpsace -> workspace (user reported misspell)
    original_path = remote_path
    remote_path = remote_path.replace('/worksapce/', '/workspace/').replace('/worspace/', '/workspace/').replace('/workpace/', '/workspace/').replace('/workpsace/', '/workspace/')
    if original_path != remote_path:
        print(f"Corrected typo in remote_path: {original_path} -> {remote_path}")

    sb = await modal.Sandbox.from_id.aio(sandbox_id)

    # Ensure parent dirs exist via mkdir -p (fixes fallback generic path parent missing like /workspace/tasks/23)
    import os
    parent_dir = os.path.dirname(remote_path)
    if parent_dir and parent_dir != "/" and parent_dir != "/workspace":
        try:
            # Try to create parent dir via exec mkdir -p
            p = await sb.exec.aio("bash", "-c", f"mkdir -p {parent_dir} && echo created {parent_dir}")
            mkdir_out = await p.stdout.read.aio()
            await p.wait.aio()
            print(f"mkdir -p {parent_dir} in sandbox {sandbox_id}: {mkdir_out[:200]}")
        except Exception as mkdir_e:
            print(f"mkdir -p {parent_dir} failed (non-fatal, will try write anyway): {mkdir_e}")

    print(f"🧠 Trying to create file {remote_path} in sandbox {sandbox_id} - {len(content)} chars - new file if not exists (write_text_to_sandbox)")
    await sb.filesystem.write_text.aio(content, remote_path)
    print(f"✅ Created file {remote_path} in sandbox {sandbox_id} - wrote {len(content)} chars")
    request_log = f"""# Write text to sandbox via filesystem API (no volume, per-project) - creates new file if not exists
# Stripped # File: line from code (per user: should not be part of code)
# Corrected typo worksapce->workspace if needed
# Ensured parent dir exists via mkdir -p {parent_dir}
sb = await modal.Sandbox.from_id.aio("{sandbox_id}")
await sb.exec.aio("bash", "-c", "mkdir -p {parent_dir}")
await sb.filesystem.write_text.aio(\"\"\"{content[:100]}...\"\"\", "{remote_path}")
# File now exists at {remote_path} and is accessible via tunnel if http server running
"""
    print(request_log)
    return {"written": True, "remote_path": remote_path, "sandbox_id": sandbox_id, "request_log": request_log, "original_path": original_path, "corrected": original_path != remote_path}

def write_text_to_sandbox(sandbox_id: str, content: str, remote_path: str) -> Dict:
    return _run_sync(lambda: write_text_to_sandbox_async(sandbox_id, content, remote_path))

async def list_files_in_sandbox_async(sandbox_id: str, path: str = "/workspace") -> Dict:
    """List files in sandbox via filesystem API - per-project path"""
    sb = await modal.Sandbox.from_id.aio(sandbox_id)
    entries = await sb.filesystem.list_files.aio(path)
    files = [{"name": e.name, "type": e.type.value if hasattr(e.type, 'value') else str(e.type), "size": e.size, "path": f"{path.rstrip('/')}/{e.name}"} for e in entries]

    request_log = f"""# List files in sandbox (per-project, no volume)
sb = await modal.Sandbox.from_id.aio("{sandbox_id}")
for entry in await sb.filesystem.list_files.aio("{path}"):
    print(entry.name, entry.type.value, entry.size)
"""

    return {"files": files, "path": path, "sandbox_id": sandbox_id, "request_log": request_log}

def list_files_in_sandbox(sandbox_id: str, path: str = "/workspace") -> Dict:
    return _run_sync(lambda: list_files_in_sandbox_async(sandbox_id, path))

async def read_file_from_sandbox_async(sandbox_id: str, remote_path: str) -> Dict:
    sb = await modal.Sandbox.from_id.aio(sandbox_id)
    content = await sb.filesystem.read_text.aio(remote_path)
    return {"content": content, "remote_path": remote_path, "sandbox_id": sandbox_id}

def read_file_from_sandbox(sandbox_id: str, remote_path: str) -> Dict:
    return _run_sync(lambda: read_file_from_sandbox_async(sandbox_id, remote_path))

async def clone_repo_in_sandbox_async(sandbox_id: str, repo_url: str, branch: str = "main", target_dir: str = "/workspace/repo") -> Dict:
    """Git repo handling per-project"""
    sb = await modal.Sandbox.from_id.aio(sandbox_id)
    cmd = f"git clone {repo_url} {target_dir} --branch {branch} 2>&1 || git -C {target_dir} pull 2>&1"
    p = await sb.exec.aio("bash", "-c", cmd)
    output = await p.stdout.read.aio()
    await p.wait.aio()

    request_log = f"""# Git repo handling per-project
sb = await modal.Sandbox.from_id.aio("{sandbox_id}")
p = await sb.exec.aio("bash", "-c", "git clone {repo_url} {target_dir} --branch {branch} || git -C {target_dir} pull")
print(await p.stdout.read.aio())
"""

    return {
        "cloned": True,
        "repo_url": repo_url,
        "branch": branch,
        "target_dir": target_dir,
        "output": output,
        "returncode": p.returncode,
        "request_log": request_log,
        "sandbox_id": sandbox_id
    }

def clone_repo_in_sandbox(sandbox_id: str, repo_url: str, branch: str = "main", target_dir: str = "/workspace/repo") -> Dict:
    return _run_sync(lambda: clone_repo_in_sandbox_async(sandbox_id, repo_url, branch, target_dir))

async def find_file_in_sandbox_async(sandbox_id: str, filename: str, search_root: str = "/workspace", limit: int = 5) -> Dict:
    """Locate a bare filename (e.g. contact.html) under /workspace via find."""
    import os
    base = os.path.basename((filename or "").strip())
    if not base:
        return {"matches": [], "filename": filename}
    sb = await modal.Sandbox.from_id.aio(sandbox_id)
    cmd = f"find {search_root} -name {base} 2>/dev/null | head -n {limit}"
    p = await sb.exec.aio("bash", "-c", cmd)
    output = (await p.stdout.read.aio()) or ""
    await p.wait.aio()
    matches = [line.strip() for line in output.splitlines() if line.strip()]
    return {"matches": matches, "filename": base, "sandbox_id": sandbox_id}

def find_file_in_sandbox(sandbox_id: str, filename: str, search_root: str = "/workspace", limit: int = 5) -> Dict:
    return _run_sync(lambda: find_file_in_sandbox_async(sandbox_id, filename, search_root, limit))

async def delete_file_in_sandbox_async(sandbox_id: str, remote_path: str) -> Dict:
    """Delete a file in the sandbox (user asked to delete, not create)."""
    if not remote_path or not remote_path.startswith("/workspace/"):
        return {"deleted": False, "remote_path": remote_path, "error": "only /workspace paths may be deleted"}
    sb = await modal.Sandbox.from_id.aio(sandbox_id)
    p = await sb.exec.aio("bash", "-c", f"rm -f {remote_path} && echo deleted {remote_path}")
    output = (await p.stdout.read.aio()) or ""
    await p.wait.aio()
    return {"deleted": True, "remote_path": remote_path, "sandbox_id": sandbox_id, "output": output}

def delete_file_in_sandbox(sandbox_id: str, remote_path: str) -> Dict:
    return _run_sync(lambda: delete_file_in_sandbox_async(sandbox_id, remote_path))

async def exec_command_in_sandbox_async(sandbox_id: str, command: str, timeout: int = 60) -> Dict:
    """Run a shell command in the sandbox (tests, ls, cat) - for 'just test it' requests."""
    sb = await modal.Sandbox.from_id.aio(sandbox_id)
    p = await sb.exec.aio("bash", "-c", command)
    output = (await p.stdout.read.aio()) or ""
    await p.wait.aio()
    return {"output": output[:6000], "returncode": p.returncode, "command": command, "sandbox_id": sandbox_id}

def exec_command_in_sandbox(sandbox_id: str, command: str, timeout: int = 60) -> Dict:
    return _run_sync(lambda: exec_command_in_sandbox_async(sandbox_id, command, timeout))
