import sys
from pathlib import Path
from flask import Flask
from .config import Config
from .routes.web import web_bp
from .routes.api import api_bp


def _resource_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "app"
    return Path(__file__).resolve().parent


def create_app(config_class=Config):
    root = _resource_root()
    app = Flask(
        __name__,
        template_folder=str(root / "templates"),
        static_folder=str(root / "static"),
    )
    app.config.from_object(config_class)
    Config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp)
    from .routes.ai_report import ai_report_bp  # AI results reports
    app.register_blueprint(ai_report_bp)
    from .security import init_security  # web login (server mode only)
    init_security(app)
    return app
