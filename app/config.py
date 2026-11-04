import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'codefactory-secret-key-change-in-prod')
    basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f"sqlite:///{os.path.join(basedir, 'codefactory.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    WTF_CSRF_ENABLED = True

    # Modal.com integration
    MODAL_WORKSPACE_ID = os.environ.get('MODAL_WORKSPACE_ID') or os.environ.get('MODAL_WORDSPACE_ID')
    MODAL_TOKEN_ID = os.environ.get('MODAL_TOKEN_ID')
    MODAL_TOKEN_SECRET = os.environ.get('MODAL_TOKEN_SECRET')
    MODAL_ENV = os.environ.get('MODAL_ENV', 'codefactory-platform')
    
    # Modal - Path A only (everything in codefactoryverse, no modal_app.py)
    MODAL_PROXY_TOKEN_ID = os.environ.get('MODAL_KEY') or os.environ.get('MODAL_PROXY_TOKEN_ID')  # wk-...
    MODAL_PROXY_TOKEN_SECRET = os.environ.get('MODAL_SECRETE') or os.environ.get('MODAL_PROXY_TOKEN_SECRET')  # ws-...
    MODAL_ENDPOINT_HOST = os.environ.get('MODAL_ENDPOINT_HOST')  # e.g. my-qwen--qwen3-8b-xxx.modal.run or my-endpoint.us-west.modal.direct

    # Voice - Meta Muse STT + Cartesia TTS
    CARTESIA_API_KEY = os.environ.get('CARTESIA_API_KEY')
    
    # LLM Keys (generic)
    MODEL_API_KEY = os.environ.get('MODEL_API_KEY')
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    
    @property
    def modal_proxy_auth(self):
        """Returns Bearer token for Modal endpoints if both parts present"""
        if self.MODAL_PROXY_TOKEN_ID and self.MODAL_PROXY_TOKEN_SECRET:
            return f"{self.MODAL_PROXY_TOKEN_ID.strip()}.{self.MODAL_PROXY_TOKEN_SECRET.strip()}"
        auth = os.environ.get('AUTHORIZATION', '')
        if auth:
            return auth.replace('Bearer', '').strip()
        return None

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False
