"""Central Flask extension instances — imported everywhere to avoid circular imports."""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[], strategy='fixed-window')
talisman = Talisman()

login_manager.login_view = 'auth.login'
login_manager.login_message = 'Bitte melde dich an, um fortzufahren.'
login_manager.login_message_category = 'warning'
