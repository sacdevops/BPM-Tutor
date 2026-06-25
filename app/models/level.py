"""CMS database models — Learning Level & UserLevelProgress."""
from datetime import datetime, timezone

from app.extensions import db


level_tasks = db.Table(
    'level_tasks',
    db.Column('level_id', db.Integer, db.ForeignKey('learning_levels.id', ondelete='CASCADE'), primary_key=True),
    db.Column('task_id', db.String(100), db.ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True),
)


class LearningLevel(db.Model):
    """A sequential learning level that students must complete in order."""
    __tablename__ = 'learning_levels'

    id = db.Column(db.Integer, primary_key=True)
    level_number = db.Column(db.Integer, nullable=False, unique=True)  # 1, 2, 3, …
    title = db.Column(db.String(200), nullable=False)
    title_de = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=True)
    description_de = db.Column(db.Text, nullable=True)

    difficulty = db.Column(db.String(20), nullable=False, default='beginner') # values: beginner | intermediate | advanced | expert

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    tasks = db.relationship('Task', secondary=level_tasks, backref='levels', lazy='dynamic')
    progress = db.relationship('UserLevelProgress', back_populates='level', lazy='dynamic',
                               cascade='all, delete-orphan')

    @property
    def display_title(self) -> str:
        """Title with level number prefix."""
        return f'Level {self.level_number}: {self.title}'

    @property
    def task_count(self) -> int:
        return self.tasks.count()

    @property
    def required_completions(self) -> int:
        """Number of tasks required to unlock next level (all tasks in this level)."""
        return self.task_count

    def is_unlocked_for(self, user) -> bool:
        """Level 1 is always unlocked; higher levels require the previous level to be completed."""
        if self.level_number == 1:
            return True
        prev = LearningLevel.query.filter_by(level_number=self.level_number - 1).first()
        if prev is None:
            return True
        return prev.is_completed_by(user)

    def is_completed_by(self, user) -> bool:
        """All active tasks in this level have been submitted (any submission counts)."""
        if self.task_count == 0:
            return False
        from app.models.task import TaskSubmission
        task_ids = [t.id for t in self.tasks.filter_by(is_active=True).all()]
        if not task_ids:
            return False
        completed_ids = {
            s.task_id for s in TaskSubmission.query.filter(
                TaskSubmission.user_id == user.id,
                TaskSubmission.task_id.in_(task_ids)
            ).all()
        }
        return all(tid in completed_ids for tid in task_ids)

    def completion_ratio_for(self, user) -> tuple[int, int]:
        """Returns (completed_count, total_count) for this user."""
        from app.models.task import TaskSubmission
        task_ids = [t.id for t in self.tasks.filter_by(is_active=True).all()]
        total = len(task_ids)
        if total == 0:
            return 0, 0
        completed_count = TaskSubmission.query.filter(
            TaskSubmission.user_id == user.id,
            TaskSubmission.task_id.in_(task_ids)
        ).distinct(TaskSubmission.task_id).count()
        return completed_count, total


class UserLevelProgress(db.Model):
    """Tracks when a user completes a level."""
    __tablename__ = 'user_level_progress'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    level_id = db.Column(db.Integer, db.ForeignKey('learning_levels.id', ondelete='CASCADE'), nullable=False)
    completed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (db.UniqueConstraint('user_id', 'level_id', name='uq_user_level'),)

    user = db.relationship('User', backref=db.backref('level_progress', lazy='dynamic'))
    level = db.relationship('LearningLevel', back_populates='progress')
