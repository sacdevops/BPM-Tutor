"""CMS model — Cohorts (named groups of users)."""
from datetime import datetime

from cms.extensions import db


class Cohort(db.Model):
    __tablename__ = 'cohorts'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    memberships = db.relationship(
        'CohortMembership', backref='cohort',
        cascade='all, delete-orphan', lazy='dynamic'
    )
    creator = db.relationship('User', foreign_keys=[created_by_id])

    @property
    def member_count(self) -> int:
        return self.memberships.count()

    def has_user(self, user_id: int) -> bool:
        return self.memberships.filter_by(user_id=user_id).first() is not None

    def __repr__(self) -> str:
        return f'<Cohort {self.id} {self.name!r}>'


class CohortMembership(db.Model):
    __tablename__ = 'cohort_memberships'

    id = db.Column(db.Integer, primary_key=True)
    cohort_id = db.Column(db.Integer, db.ForeignKey('cohorts.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (db.UniqueConstraint('cohort_id', 'user_id', name='uq_cohort_user'),)

    def __repr__(self) -> str:
        return f'<CohortMembership cohort={self.cohort_id} user={self.user_id}>'
