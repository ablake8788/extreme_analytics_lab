from flask import Blueprint, render_template
from app.config import Config

web_bp = Blueprint("web", __name__)


@web_bp.get("/")
def index():
    return render_template("index.html", defaults=Config)
