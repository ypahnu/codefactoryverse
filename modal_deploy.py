"""Deploy CodeFactory Flask app to Modal (online for people to use).

NOTE: this is only the *hosting* entrypoint (Flask via wsgi_app). It is not
the old deleted Modal inference modal_app.py - Path A inference stays as-is.

Usage (from this folder, on a machine with network + `modal setup` done):
  modal secret create codefactory-secrets SECRET_KEY=<random-hex> ...
  modal deploy -e codefactoryverse modal_deploy.py

Secrets read by app/config.py - set whichever features you need:
  SECRET_KEY (required, random hex), DATABASE_URL (optional, sqlite default),
  MODEL_API_KEY, CARTESIA_API_KEY, MODAL_* (inference endpoint / sandbox).
"""
import modal

app = modal.App("codefactoryverse")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir(
        ".",
        remote_path="/root/codefactoryverse",
        ignore=["codefactory.db", "*.db", ".env", "__pycache__", "uploads"],
    )
)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("codefactory-secrets")],
)
@modal.wsgi_app()
def flask_app():
    import os
    import sys

    sys.path.insert(0, "/root/codefactoryverse")
    os.chdir("/root/codefactoryverse")
    for d in ("uploads/voice", "uploads/sandbox"):
        os.makedirs(d, exist_ok=True)
    from app import create_app

    return create_app()
