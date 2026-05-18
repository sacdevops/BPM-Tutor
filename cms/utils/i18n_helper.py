"""Server-side i18n helper.

Usage in Python:
    from cms.utils.i18n_helper import _t
    msg = _t('flash.saved', 'Gespeichert')

Usage in Jinja2 templates (auto-registered as global):
    {{ _t('nav.users') }}
    {{ _t('greeting', name=user.display_name) }}

The current language is read from ``flask.g.user_lang`` (set by the
``set_user_lang`` before_request hook in cms/__init__.py).

Fallback chain:
  1. Look up (g.user_lang, key)
  2. Look up (default_language, key)
  3. Return ``default`` argument or the key itself
"""
from __future__ import annotations

import threading
from typing import Optional

# Module-level cache:  { lang_code: { key: value } }
_cache: dict[str, dict[str, str]] = {}
_cache_lock = threading.Lock()
_default_lang: str = 'en'


# ── public API ───────────────────────────────────────────────────────────────

def _t(key: str, default: str | None = None, **kwargs) -> str:
    """Translate *key* for the current request language."""
    try:
        from flask import g
        lang = getattr(g, 'user_lang', _default_lang)
    except RuntimeError:
        lang = _default_lang

    value = _lookup(lang, key) or _lookup(_default_lang, key)
    if value is None:
        value = default if default is not None else key

    if kwargs:
        try:
            value = value.format(**kwargs)
        except (KeyError, IndexError):
            pass

    return value


def invalidate_cache() -> None:
    """Clear the in-memory string cache (call after DB edits)."""
    with _cache_lock:
        _cache.clear()


def warm_cache() -> None:
    """Pre-load all language strings into memory. Safe to call multiple times."""
    try:
        from cms.models.i18n import Language, LanguageString
        global _default_lang
        with _cache_lock:
            _cache.clear()
            langs = Language.query.filter_by(is_active=True).all()
            for lang in langs:
                if lang.is_default:
                    _default_lang = lang.code
                rows = LanguageString.query.filter_by(language_code=lang.code).all()
                _cache[lang.code] = {r.key: r.value for r in rows}
    except Exception:
        pass  # DB may not be ready yet


# ── internal ─────────────────────────────────────────────────────────────────

def _lookup(lang: str, key: str) -> str | None:
    with _cache_lock:
        lang_dict = _cache.get(lang)
        if lang_dict is None:
            return None
        return lang_dict.get(key)


# ── seeding ──────────────────────────────────────────────────────────────────

DE_STRINGS: dict[str, str] = {
    # Navigation
    'nav.home': 'Startseite',
    'nav.administration': 'Administration',
    'nav.system': 'System',
    'nav.dashboard': 'Dashboard',
    'nav.users': 'Benutzer',
    'nav.tasks': 'Aufgaben',
    'nav.grading': 'Bewertungen',
    'nav.surveys': 'Umfragen',
    'nav.cohorts': 'Kohorten',
    'nav.audit_log': 'Audit-Log',
    'nav.analytics': 'Analytik',
    'nav.languages': 'Sprachen & Texte',
    'nav.settings': 'Einstellungen',
    'nav.reg_fields': 'Registrierungsfelder',
    'nav.my_account': 'Mein Konto',
    'nav.my_profile': 'Profil',
    'nav.my_stats': 'Meine Statistik',
    'nav.notifications': 'Benachrichtigungen',
    'nav.my_submissions': 'Meine Einreichungen',
    'nav.logout': 'Abmelden',
    'nav.login': 'Anmelden',
    # Common
    'common.save': 'Speichern',
    'common.cancel': 'Abbrechen',
    'common.delete': 'Löschen',
    'common.edit': 'Bearbeiten',
    'common.create': 'Erstellen',
    'common.back': 'Zurück',
    'common.search': 'Suchen',
    'common.filter': 'Filtern',
    'common.yes': 'Ja',
    'common.no': 'Nein',
    'common.active': 'Aktiv',
    'common.inactive': 'Inaktiv',
    'common.actions': 'Aktionen',
    'common.all': 'Alle',
    'common.none': 'Keine',
    'common.loading': 'Wird geladen…',
    'common.confirm_delete': 'Wirklich löschen?',
    'common.required': 'Pflichtfeld',
    'common.optional': 'Optional',
    'common.true': 'Ja',
    'common.false': 'Nein',
    'common.per_page': 'pro Seite',
    'common.page': 'Seite',
    'common.of': 'von',
    'common.next': 'Weiter',
    'common.previous': 'Zurück',
    'common.export': 'Exportieren',
    'common.download': 'Herunterladen',
    'common.apply': 'Anwenden',
    'common.select_all': 'Alle auswählen',
    'common.deselect_all': 'Auswahl aufheben',
    'common.bulk_action': 'Massenaktion',
    'common.selected': 'ausgewählt',
    # Auth
    'auth.login': 'Anmelden',
    'auth.logout': 'Abmelden',
    'auth.register': 'Registrieren',
    'auth.email': 'E-Mail-Adresse',
    'auth.password': 'Passwort',
    'auth.username': 'Benutzername',
    'auth.forgot_password': 'Passwort vergessen?',
    'auth.reset_password': 'Passwort zurücksetzen',
    'auth.verify_email': 'E-Mail bestätigen',
    # Users
    'users.title': 'Benutzer',
    'users.create': 'Benutzer erstellen',
    'users.role': 'Rolle',
    'users.admin': 'Administrator',
    'users.instructor': 'Lehrende/r',
    'users.student': 'Studierende/r',
    'users.status': 'Status',
    'users.verified': 'Verifiziert',
    'users.locked': 'Gesperrt',
    'users.created_at': 'Erstellt am',
    'users.last_login': 'Letzter Login',
    'users.profile': 'Profil',
    'users.language': 'Sprache',
    'users.api_key': 'API-Schlüssel',
    # Tasks
    'tasks.title': 'Aufgaben',
    'tasks.create': 'Aufgabe erstellen',
    'tasks.description': 'Beschreibung',
    'tasks.grading': 'Bewertung',
    'tasks.available_from': 'Verfügbar ab',
    'tasks.available_until': 'Verfügbar bis',
    'tasks.prerequisites': 'Voraussetzungen',
    'tasks.sort_order': 'Reihenfolge',
    'tasks.active': 'Aktiv',
    'tasks.no_grading': 'Keine Bewertung',
    'tasks.points': 'Punkte',
    'tasks.pass_fail': 'Bestanden / Nicht bestanden',
    'tasks.additional_languages': 'Weitere Sprachen',
    # Grading
    'grading.title': 'Bewertungen',
    'grading.grade': 'Bewerten',
    'grading.points': 'Punkte',
    'grading.pass_fail': 'Bestanden / Nicht bestanden',
    'grading.pass': 'Bestanden',
    'grading.fail': 'Nicht bestanden',
    'grading.comment': 'Kommentar',
    'grading.save': 'Bewertung speichern',
    'grading.ai_suggestion': 'KI-Vorschlag',
    'grading.ai_generate': 'KI-Bewertung generieren',
    'grading.annotations': 'Anmerkungen am Diagramm',
    'grading.notify_student': 'Studierende/n benachrichtigen',
    # Analytics
    'analytics.title': 'Analytik',
    'analytics.submissions': 'Einreichungen',
    'analytics.completed': 'Abgeschlossen',
    'analytics.tokens': 'Token verwendet',
    'analytics.interactions': 'Interaktionen',
    'analytics.avg_duration': 'Ø Bearbeitungszeit',
    'analytics.bpmn_errors': 'Häufigste BPMN-Fehler',
    'analytics.per_task': 'Pro Aufgabe',
    'analytics.per_cohort': 'Pro Kohorte',
    # Cohorts
    'cohorts.title': 'Kohorten',
    'cohorts.create': 'Kohorte erstellen',
    'cohorts.name': 'Name',
    'cohorts.description': 'Beschreibung',
    'cohorts.members': 'Mitglieder',
    'cohorts.add_member': 'Mitglied hinzufügen',
    'cohorts.remove_member': 'Entfernen',
    # Audit
    'audit.title': 'Audit-Log',
    'audit.action': 'Aktion',
    'audit.user': 'Benutzer',
    'audit.entity': 'Objekt',
    'audit.time': 'Zeitpunkt',
    'audit.ip': 'IP-Adresse',
    'audit.details': 'Details',
    # Prerequisites
    'prereq.title': 'Voraussetzungen',
    'prereq.add_rule': 'Regel hinzufügen',
    'prereq.connector_and': 'Alle Bedingungen erfüllen (UND)',
    'prereq.connector_or': 'Mindestens eine Bedingung (ODER)',
    'prereq.field.task_completed': 'Aufgabe abgeschlossen',
    'prereq.field.task_submitted': 'Aufgabe eingereicht',
    'prereq.field.cohort_member': 'Mitglied in Kohorte',
    'prereq.field.role': 'Rolle hat Wert',
    'prereq.op.eq': 'ist',
    'prereq.op.neq': 'ist nicht',
    # Export
    'export.title': 'Daten exportieren',
    'export.format': 'Format',
    'export.include_bpmn': 'BPMN-Dateien einschließen',
    'export.include_chatlogs': 'Chat-Verläufe einschließen',
    'export.generate': 'Export erstellen',
    # Languages admin
    'lang_admin.title': 'Sprachen & Übersetzungen',
    'lang_admin.add_language': 'Sprache hinzufügen',
    'lang_admin.code': 'Sprachcode',
    'lang_admin.name': 'Name',
    'lang_admin.is_default': 'Standard',
    'lang_admin.edit_strings': 'Texte bearbeiten',
    'lang_admin.key': 'Schlüssel',
    'lang_admin.value': 'Wert',
    'lang_admin.add_string': 'Eintrag hinzufügen',
    # Profile
    'profile.title': 'Mein Profil',
    'profile.language': 'Anzeigesprache',
    'profile.change_password': 'Passwort ändern',
    'profile.current_password': 'Aktuelles Passwort',
    'profile.new_password': 'Neues Passwort',
    'profile.save': 'Profil speichern',
    # Flash / system messages
    'flash.saved': 'Gespeichert.',
    'flash.deleted': 'Gelöscht.',
    'flash.error': 'Fehler.',
    'flash.created': 'Erstellt.',
    'flash.updated': 'Aktualisiert.',
    'flash.unauthorized': 'Keine Berechtigung.',
    'flash.not_found': 'Nicht gefunden.',
}

EN_STRINGS: dict[str, str] = {
    'nav.home': 'Home',
    'nav.administration': 'Administration',
    'nav.system': 'System',
    'nav.dashboard': 'Dashboard',
    'nav.users': 'Users',
    'nav.tasks': 'Tasks',
    'nav.grading': 'Grading',
    'nav.surveys': 'Surveys',
    'nav.cohorts': 'Cohorts',
    'nav.audit_log': 'Audit Log',
    'nav.analytics': 'Analytics',
    'nav.languages': 'Languages & Texts',
    'nav.settings': 'Settings',
    'nav.reg_fields': 'Registration Fields',
    'nav.my_account': 'My Account',
    'nav.my_profile': 'Profile',
    'nav.my_stats': 'My Statistics',
    'nav.notifications': 'Notifications',
    'nav.my_submissions': 'My Submissions',
    'nav.logout': 'Logout',
    'nav.login': 'Login',
    'common.save': 'Save',
    'common.cancel': 'Cancel',
    'common.delete': 'Delete',
    'common.edit': 'Edit',
    'common.create': 'Create',
    'common.back': 'Back',
    'common.search': 'Search',
    'common.filter': 'Filter',
    'common.yes': 'Yes',
    'common.no': 'No',
    'common.active': 'Active',
    'common.inactive': 'Inactive',
    'common.actions': 'Actions',
    'common.all': 'All',
    'common.none': 'None',
    'common.loading': 'Loading…',
    'common.confirm_delete': 'Really delete?',
    'common.required': 'Required',
    'common.optional': 'Optional',
    'common.true': 'Yes',
    'common.false': 'No',
    'common.per_page': 'per page',
    'common.page': 'Page',
    'common.of': 'of',
    'common.next': 'Next',
    'common.previous': 'Previous',
    'common.export': 'Export',
    'common.download': 'Download',
    'common.apply': 'Apply',
    'common.select_all': 'Select all',
    'common.deselect_all': 'Deselect all',
    'common.bulk_action': 'Bulk action',
    'common.selected': 'selected',
    'auth.login': 'Login',
    'auth.logout': 'Logout',
    'auth.register': 'Register',
    'auth.email': 'Email address',
    'auth.password': 'Password',
    'auth.username': 'Username',
    'auth.forgot_password': 'Forgot password?',
    'auth.reset_password': 'Reset password',
    'auth.verify_email': 'Verify email',
    'users.title': 'Users',
    'users.create': 'Create user',
    'users.role': 'Role',
    'users.admin': 'Administrator',
    'users.instructor': 'Instructor',
    'users.student': 'Student',
    'users.status': 'Status',
    'users.verified': 'Verified',
    'users.locked': 'Locked',
    'users.created_at': 'Created at',
    'users.last_login': 'Last login',
    'users.profile': 'Profile',
    'users.language': 'Language',
    'users.api_key': 'API key',
    'tasks.title': 'Tasks',
    'tasks.create': 'Create task',
    'tasks.description': 'Description',
    'tasks.grading': 'Grading',
    'tasks.available_from': 'Available from',
    'tasks.available_until': 'Available until',
    'tasks.prerequisites': 'Prerequisites',
    'tasks.sort_order': 'Sort order',
    'tasks.active': 'Active',
    'tasks.no_grading': 'No grading',
    'tasks.points': 'Points',
    'tasks.pass_fail': 'Pass / Fail',
    'tasks.additional_languages': 'Additional Languages',
    'grading.title': 'Grading',
    'grading.grade': 'Grade',
    'grading.points': 'Points',
    'grading.pass_fail': 'Pass / Fail',
    'grading.pass': 'Pass',
    'grading.fail': 'Fail',
    'grading.comment': 'Comment',
    'grading.save': 'Save grade',
    'grading.ai_suggestion': 'AI suggestion',
    'grading.ai_generate': 'Generate AI grade',
    'grading.annotations': 'Diagram annotations',
    'grading.notify_student': 'Notify student',
    'analytics.title': 'Analytics',
    'analytics.submissions': 'Submissions',
    'analytics.completed': 'Completed',
    'analytics.tokens': 'Tokens used',
    'analytics.interactions': 'Interactions',
    'analytics.avg_duration': 'Avg. duration',
    'analytics.bpmn_errors': 'Most frequent BPMN errors',
    'analytics.per_task': 'Per task',
    'analytics.per_cohort': 'Per cohort',
    'cohorts.title': 'Cohorts',
    'cohorts.create': 'Create cohort',
    'cohorts.name': 'Name',
    'cohorts.description': 'Description',
    'cohorts.members': 'Members',
    'cohorts.add_member': 'Add member',
    'cohorts.remove_member': 'Remove',
    'audit.title': 'Audit Log',
    'audit.action': 'Action',
    'audit.user': 'User',
    'audit.entity': 'Entity',
    'audit.time': 'Time',
    'audit.ip': 'IP address',
    'audit.details': 'Details',
    'prereq.title': 'Prerequisites',
    'prereq.add_rule': 'Add rule',
    'prereq.connector_and': 'All conditions must be met (AND)',
    'prereq.connector_or': 'At least one condition (OR)',
    'prereq.field.task_completed': 'Task completed',
    'prereq.field.task_submitted': 'Task submitted',
    'prereq.field.cohort_member': 'Member of cohort',
    'prereq.field.role': 'Role equals',
    'prereq.op.eq': 'is',
    'prereq.op.neq': 'is not',
    'export.title': 'Export data',
    'export.format': 'Format',
    'export.include_bpmn': 'Include BPMN files',
    'export.include_chatlogs': 'Include chat logs',
    'export.generate': 'Generate export',
    'lang_admin.title': 'Languages & Translations',
    'lang_admin.add_language': 'Add language',
    'lang_admin.code': 'Language code',
    'lang_admin.name': 'Name',
    'lang_admin.is_default': 'Default',
    'lang_admin.edit_strings': 'Edit strings',
    'lang_admin.key': 'Key',
    'lang_admin.value': 'Value',
    'lang_admin.add_string': 'Add entry',
    'profile.title': 'My Profile',
    'profile.language': 'Display language',
    'profile.change_password': 'Change password',
    'profile.current_password': 'Current password',
    'profile.new_password': 'New password',
    'profile.save': 'Save profile',
    'flash.saved': 'Saved.',
    'flash.deleted': 'Deleted.',
    'flash.error': 'Error.',
    'flash.created': 'Created.',
    'flash.updated': 'Updated.',
    'flash.unauthorized': 'Unauthorized.',
    'flash.not_found': 'Not found.',
}


def seed_languages() -> None:
    """Insert DE and EN languages with their strings if not present."""
    try:
        from cms.extensions import db
        from cms.models.i18n import Language, LanguageString

        # German
        de = Language.query.get('de')
        if de is None:
            de = Language(code='de', name='Deutsch', flag='🇩🇪',
                          is_active=True, is_default=False, sort_order=1)
            db.session.add(de)
            db.session.flush()

        # English (default)
        en = Language.query.get('en')
        if en is None:
            en = Language(code='en', name='English', flag='\U0001f1ec\U0001f1e7',
                          is_active=True, is_default=True, sort_order=0)
            db.session.add(en)
            db.session.flush()
        else:
            # Ensure EN is default if DE was set as default initially
            if not en.is_default and not Language.query.filter_by(is_default=True).first():
                en.is_default = True

        # Seed strings (skip existing ones)
        for code, strings in [('de', DE_STRINGS), ('en', EN_STRINGS)]:
            existing_keys = {
                r.key for r in LanguageString.query.filter_by(language_code=code).all()
            }
            for key, value in strings.items():
                if key not in existing_keys:
                    db.session.add(LanguageString(language_code=code, key=key, value=value))

        db.session.commit()
        warm_cache()
    except Exception as exc:
        try:
            from flask import current_app
            current_app.logger.warning('[i18n] seed_languages failed: %s', exc)
        except Exception:
            pass
