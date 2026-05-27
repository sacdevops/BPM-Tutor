"""CMS model — Configurable server-side internationalization."""
from datetime import datetime

from app.extensions import db


class Language(db.Model):
    __tablename__ = 'languages'

    code = db.Column(db.String(10), primary_key=True)   # e.g. 'de', 'en'
    name = db.Column(db.String(100), nullable=False)    # e.g. 'Deutsch', 'English'
    flag = db.Column(db.String(10), nullable=True)      # emoji or icon key, optional
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    strings = db.relationship(
        'LanguageString', backref='language',
        cascade='all, delete-orphan', lazy='dynamic'
    )

    def __repr__(self) -> str:
        return f'<Language {self.code}>'


class LanguageString(db.Model):
    __tablename__ = 'language_strings'

    id = db.Column(db.Integer, primary_key=True)
    language_code = db.Column(
        db.String(10), db.ForeignKey('languages.code', ondelete='CASCADE'),
        nullable=False, index=True
    )
    key = db.Column(db.String(200), nullable=False, index=True)
    value = db.Column(db.Text, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('language_code', 'key', name='uq_lang_key'),
    )

    def __repr__(self) -> str:
        return f'<LanguageString {self.language_code}/{self.key}>'
