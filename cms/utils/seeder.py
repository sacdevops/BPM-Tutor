"""Seed the database from config.TASKS on first run."""
from __future__ import annotations


def seed_tasks_from_config() -> int:
    """
    Import tasks from config.TASKS into the Task table if they don't exist yet.
    Returns the number of tasks inserted.
    """
    import config as app_config
    from cms.extensions import db
    from cms.models.task import Task

    inserted = 0
    for raw in getattr(app_config, 'TASKS', []):
        task_id = raw.get('id')
        if not task_id:
            continue
        if Task.query.get(task_id) is None:
            task = Task(
                id=task_id,
                title=raw.get('title', task_id),
                title_de=raw.get('title_de'),
                description=raw.get('description', ''),
                description_de=raw.get('description_de'),
                sort_order=inserted,
                is_active=True,
            )
            db.session.add(task)
            inserted += 1

    if inserted:
        db.session.commit()

    return inserted


def create_default_admin() -> bool:
    """
    Create the first admin user from environment variables or default credentials.
    Returns True if admin was created, False if one already exists.
    """
    import os
    from cms.extensions import db
    from cms.models.user import User

    if User.query.filter_by(role='admin').first():
        return False

    email = os.getenv('ADMIN_EMAIL', 'admin@bpmtutor.local')
    username = os.getenv('ADMIN_USERNAME', 'admin')
    password = os.getenv('ADMIN_PASSWORD', 'admin1234!')

    admin = User(
        email=email,
        username=username,
        role='admin',
        is_active=True,
        is_verified=True,
        data_consent=True,
    )
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()

    print(f'[BPM-Tutor] Default admin created: {email} / {password}')
    print('[BPM-Tutor] IMPORTANT: Change the admin password after first login!')
    return True
