import os
from flask import Flask
from dotenv import load_dotenv
# Load .env from both project root and app dir
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env'))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

from .config import DevelopmentConfig
from .extensions import db, login_manager, migrate
from .models import User, Team, Project, Task, Agent, TaskMessage, MessageRead, ProjectSandbox, ProjectActivity

def create_app(config_class=DevelopmentConfig):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    # Register blueprints
    from .blueprints.auth.routes import auth_bp
    from .blueprints.dashboard.routes import dashboard_bp
    from .blueprints.teams.routes import teams_bp
    from .blueprints.projects.routes import projects_bp
    from .blueprints.projects.sandbox_routes import sandbox_bp
    from .blueprints.tasks.routes import tasks_bp
    from .blueprints.agents.routes import agents_bp
    from .blueprints.voice.routes import voice_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(dashboard_bp, url_prefix='/')
    app.register_blueprint(teams_bp, url_prefix='/teams')
    app.register_blueprint(projects_bp, url_prefix='/projects')
    app.register_blueprint(sandbox_bp, url_prefix='/projects')
    app.register_blueprint(tasks_bp, url_prefix='/projects')
    app.register_blueprint(agents_bp, url_prefix='/projects')
    app.register_blueprint(voice_bp, url_prefix='/api/voice')

    # Also alias dashboard as /dashboard
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard', name='dashboard2')

    # Template filters
    @app.template_filter('shortdate')
    def shortdate(value):
        if not value:
            return ''
        try:
            return value.strftime('%b %d, %Y')
        except:
            return str(value)

    @app.template_filter('fromjson')
    def fromjson_filter(value):
        import json
        try:
            return json.loads(value)
        except:
            return []

    # Create tables
    with app.app_context():
        db.create_all()

    return app
