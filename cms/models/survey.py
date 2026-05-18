"""CMS database models — Survey system."""
import json
from datetime import datetime

from cms.extensions import db


class Survey(db.Model):
    __tablename__ = 'surveys'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Survey placement
    # 'pre_all'     – shown once before all tasks (first visit)
    # 'post_task'   – shown after a specific task (task_id required)
    # 'post_all'    – shown after all tasks are completed
    survey_type = db.Column(db.String(30), nullable=False, index=True)

    task_id = db.Column(db.String(100), db.ForeignKey('tasks.id'), nullable=True, index=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    allow_skip = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    pages = db.relationship(
        'SurveyPage', backref='survey',
        order_by='SurveyPage.page_order',
        cascade='all, delete-orphan', lazy='select'
    )
    responses = db.relationship('SurveyResponse', backref='survey', lazy='dynamic')

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description or '',
            'survey_type': self.survey_type,
            'task_id': self.task_id or '',
            'is_active': self.is_active,
            'allow_skip': self.allow_skip,
            'pages': [p.to_dict() for p in self.pages],
        }

    def __repr__(self) -> str:
        return f'<Survey {self.id} type={self.survey_type}>'


class SurveyPage(db.Model):
    __tablename__ = 'survey_pages'

    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('surveys.id'), nullable=False, index=True)
    page_order = db.Column(db.Integer, default=0, nullable=False)
    title = db.Column(db.String(400), nullable=True)
    description = db.Column(db.Text, nullable=True)

    questions = db.relationship(
        'SurveyQuestion', backref='page',
        order_by='SurveyQuestion.sort_order',
        cascade='all, delete-orphan', lazy='select'
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'page_order': self.page_order,
            'title': self.title or '',
            'description': self.description or '',
            'questions': [q.to_dict() for q in self.questions],
        }

    def __repr__(self) -> str:
        return f'<SurveyPage {self.id} survey={self.survey_id} order={self.page_order}>'


class SurveyQuestion(db.Model):
    __tablename__ = 'survey_questions'

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey('survey_pages.id'), nullable=False, index=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    # Question types: text, textarea, likert, number, date, select, radio, checkbox, scale, info
    question_type = db.Column(db.String(30), nullable=False)

    label = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)         # helper text
    image_path = db.Column(db.String(500), nullable=True)   # optional image

    # JSON options list for select/radio/checkbox/likert: [{"value": "1", "label": "Agree"}, ...]
    options_data = db.Column(db.Text, nullable=True)

    required = db.Column(db.Boolean, default=False, nullable=False)

    # Extra config JSON: {"min": 1, "max": 10, "step": 1, "placeholder": "...", "likert_min_label": "...", "likert_max_label": "..."}
    config_data = db.Column(db.Text, nullable=True)

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

    @property
    def config(self) -> dict:
        if self.config_data:
            try:
                return json.loads(self.config_data)
            except (ValueError, TypeError):
                return {}
        return {}

    @config.setter
    def config(self, data: dict) -> None:
        self.config_data = json.dumps(data, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'sort_order': self.sort_order,
            'question_type': self.question_type,
            'type': self.question_type,  # alias used by survey_builder.js
            'label': self.label,
            'description': self.description or '',
            'image_path': self.image_path or '',
            'required': self.required,
            'options': self.options,
            'config': self.config,
        }

    def __repr__(self) -> str:
        return f'<SurveyQuestion {self.id} type={self.question_type}>'


class SurveyResponse(db.Model):
    __tablename__ = 'survey_responses'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('surveys.id'), nullable=False, index=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('task_submissions.id'), nullable=True)

    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    # JSON dict: {question_id (str): answer_value}
    answers_data = db.Column(db.Text, nullable=True)

    @property
    def answers(self) -> dict:
        if self.answers_data:
            try:
                return json.loads(self.answers_data)
            except (ValueError, TypeError):
                return {}
        return {}

    @answers.setter
    def answers(self, data: dict) -> None:
        self.answers_data = json.dumps(data, ensure_ascii=False)

    def __repr__(self) -> str:
        return f'<SurveyResponse {self.id} survey={self.survey_id} user={self.user_id}>'
