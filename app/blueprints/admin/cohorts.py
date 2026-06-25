"""Admin — cohort management and audit log routes."""
from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user

from app.blueprints.admin import admin_bp
from app.extensions import db
from app.models.user import User
from app.models.cohort import Cohort, CohortMembership
from app.models.audit import AuditLog
from app.utils.decorators import admin_required, tutor_or_admin_required
from app.utils.audit import log_action


# Cohorts

@admin_bp.route('/cohorts')
@tutor_or_admin_required
def cohorts_list():
    cohorts = Cohort.query.order_by(Cohort.created_at.desc()).all()
    return render_template('cms/admin/cohorts_list.html', cohorts=cohorts)


@admin_bp.route('/cohorts/new', methods=['GET', 'POST'])
@tutor_or_admin_required
def cohort_new():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Name erforderlich.', 'danger')
            return redirect(request.referrer or url_for('admin.cohorts_list'))
        cohort = Cohort(
            name=name,
            description=request.form.get('description', ''),
            is_active=bool(request.form.get('is_active')),
            created_by_id=current_user.id,
        )
        db.session.add(cohort)
        db.session.commit()
        log_action('create_cohort', 'Cohort', cohort.id, {'name': name})
        flash(f'Gruppe \u201e{name}\u201c erstellt.', 'success')
        return redirect(url_for('admin.cohort_detail', cohort_id=cohort.id))
    return render_template('cms/admin/cohort_detail.html', cohort=None, members=[],
                           member_ids=set(),
                           all_users=User.query.order_by(User.username).all())


@admin_bp.route('/cohorts/<int:cohort_id>', methods=['GET', 'POST'])
@tutor_or_admin_required
def cohort_detail(cohort_id: int):
    cohort = Cohort.query.get_or_404(cohort_id)
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update':
            cohort.name = request.form.get('name', cohort.name).strip()
            cohort.description = request.form.get('description', cohort.description)
            cohort.is_active = bool(request.form.get('is_active'))
            db.session.commit()
            log_action('update_cohort', 'Cohort', cohort.id, {'name': cohort.name})
            flash('Gruppe aktualisiert.', 'success')
        elif action == 'add_member':
            user_id = int(request.form.get('user_id', 0))
            if user_id and not CohortMembership.query.filter_by(
                    cohort_id=cohort_id, user_id=user_id).first():
                db.session.add(CohortMembership(cohort_id=cohort_id, user_id=user_id))
                db.session.commit()
                log_action('add_cohort_member', 'Cohort', cohort_id, {'user_id': user_id})
                flash('Mitglied hinzugefügt.', 'success')
        elif action == 'add_members_bulk':
            user_ids = request.form.getlist('user_ids[]')
            added = 0
            for uid_str in user_ids:
                try:
                    uid = int(uid_str)
                except (ValueError, TypeError):
                    continue
                if uid and not CohortMembership.query.filter_by(
                        cohort_id=cohort_id, user_id=uid).first():
                    db.session.add(CohortMembership(cohort_id=cohort_id, user_id=uid))
                    added += 1
            if added:
                db.session.commit()
                log_action('add_cohort_members_bulk', 'Cohort', cohort_id, {'count': added})
                flash(f'{added} Mitglied(er) hinzugefügt.', 'success')
            else:
                flash('Keine neuen Mitglieder ausgewählt.', 'info')
        elif action == 'remove_member':
            user_id = int(request.form.get('user_id', 0))
            m = CohortMembership.query.filter_by(
                cohort_id=cohort_id, user_id=user_id).first()
            if m:
                db.session.delete(m)
                db.session.commit()
                log_action('remove_cohort_member', 'Cohort', cohort_id, {'user_id': user_id})
                flash('Mitglied entfernt.', 'success')
        elif action == 'delete':
            db.session.delete(cohort)
            db.session.commit()
            log_action('delete_cohort', 'Cohort', cohort_id, {'name': cohort.name})
            flash('Gruppe gel\u00f6scht.', 'success')
            return redirect(url_for('admin.cohorts_list'))
        return redirect(url_for('admin.cohort_detail', cohort_id=cohort_id))

    members = (User.query
               .join(CohortMembership, CohortMembership.user_id == User.id)
               .filter(CohortMembership.cohort_id == cohort_id)
               .all())
    member_ids = {u.id for u in members}
    all_users = User.query.order_by(User.username).all()
    return render_template('cms/admin/cohort_detail.html',
                           cohort=cohort, members=members,
                           member_ids=member_ids, all_users=all_users)


# Audit log

@admin_bp.route('/audit-log')
@admin_required
def audit_log():
    page = request.args.get('page', 1, type=int)
    q = AuditLog.query.order_by(AuditLog.created_at.desc())
    action_filter = request.args.get('action', '').strip()
    user_filter = request.args.get('user_id', '')
    if action_filter:
        q = q.filter(AuditLog.action.ilike(f'%{action_filter}%'))
    if user_filter.isdigit():
        q = q.filter(AuditLog.user_id == int(user_filter))
    pagination = q.paginate(page=page, per_page=50, error_out=False)
    return render_template('cms/admin/audit_log.html',
                           pagination=pagination, entries=pagination.items,
                           action_filter=action_filter, user_filter=user_filter)
