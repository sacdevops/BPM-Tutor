"""RegistrationField model (extracted from settings.py for clarity)."""
import json

from app.extensions import db


class RegistrationField(db.Model):
    """Extra fields shown on the registration form (configurable by admin)."""
    __tablename__ = 'registration_fields'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    label = db.Column(db.String(300), nullable=False)
    label_de = db.Column(db.String(300), nullable=True)

    field_type = db.Column(db.String(30), nullable=False, default='text')

    options_data = db.Column(db.Text, nullable=True)

    required = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    @property
    def options(self) -> list:
        if self.options_data:
            try:
                return json.loads(self.options_data)
            except (ValueError, TypeError):
                return []
        return []

    @options.setter
    def options(self, data: list) -> None:
        self.options_data = json.dumps(data, ensure_ascii=False)

    def __repr__(self) -> str:
        return f'<RegistrationField {self.name}>'
