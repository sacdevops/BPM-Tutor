/**
 * BPM-Tutor — Internationalization (i18n)
 * Supports English (en) and German (de).
 */

// Sync localStorage language from the server-side cookie so that a language
// switch via the header (which sets the bpmtutor_lang cookie via /set-language)
// is immediately reflected in the client-side translation on the next page load.
(function () {
    var cookie = document.cookie.split(';').find(function (c) {
        return c.trim().startsWith('bpmtutor_lang=');
    });
    if (cookie) {
        var lang = cookie.split('=')[1].trim();
        if (lang) { localStorage.setItem('bpm-tutor-lang', lang); }
    }
})();

const FLAG_EN = '<img src="https://flagcdn.com/w20/gb.png" width="20" height="15" alt="EN">';
const FLAG_DE = '<img src="https://flagcdn.com/w20/de.png" width="20" height="15" alt="DE">';

const TRANSLATIONS = {
    en: {
        // Index page
        'index.subtitle': 'BPMN Modeling Learning Environment',
        'index.learning_path': 'Learning Path',
        'index.select_task': 'Select a Task',
        'index.custom_title': '\u270d\ufe0f Custom Task',
        'index.custom_desc': 'Define your own process. Type a description or upload a document (TXT, PDF, DOCX) \u2014 then model it yourself with Mentor guidance.',
        'index.start_custom': 'Start Custom \u2192',
        'index.start_task': 'Start Task \u2192',
        'index.continue_task': 'Continue \u2192',

        // Task page — sidebar
        'task.back': '\u2190 Back',
        'task.your_task': 'Your Task',
        'task.describe_placeholder': 'Describe your process here...',
        'task.upload_doc': '\ud83d\udcce Upload Document',
        'task.confirm_start': '\u2713 Confirm & Start',
        'task.export': '\ud83d\udce5 Export BPMN',
        'task.submit': 'Complete Task',

        // Task page — chat
        'task.mentor': '\ud83c\udf93 Mentor',
        'task.chat_placeholder': 'Ask the Mentor for help...',
        'chat.you': 'You',
        'chat.mentor': 'Mentor',
        'chat.resumed': 'Welcome back! Your progress has been restored.',
        'chat.connection_lost': '\u26a0\ufe0f Connection to server lost. Please refresh the page.',

        // Completion modal
        'task.submit_confirm_title': 'Complete Task?',
        'task.submit_confirm_msg': 'Your model still has syntax or semantic errors. Are you sure you want to complete the task?',
        'task.cancel': 'Back',
        'task.submit_btn': 'Complete',
        'task.request_review': 'Request Review',
        'task.request_completion': 'Request Completion',
        'task.approve': 'Approve',
        'task.decline': 'Decline',
        'chat.colleague_proposes_completion': 'I think we are done! Shall we complete the task?',
        'chat.decline_reason_prompt': 'Why do you want to continue? (optional)',
        'chat.decline_default': 'Let\'s continue working on the model.',

        // Issues
        'issues.title': 'Analysis Findings',
        'issues.syntax': 'Syntax',
        'issues.semantic': 'Semantic',
        'issues.best_practice': 'Best Practice',
        'issues.syntax_error': 'Syntax Error',
        'issues.semantic_issue': 'Semantic Issue',
        'issues.dismiss': 'Dismiss',
        'issues.element': 'Element:',
        'issues.category': 'Category:',
        'issues.detected': 'Issue detected',
        'issues.no_details': 'No additional details available.',

        // Custom task
        'custom.no_desc': 'Please enter a task description or upload a document.',
        'custom.title': 'Custom Task',
        'custom.file_error': 'File could not be uploaded.',
        'custom.file_read_error': 'Error reading file',

        // Auto-save & task completion
        'task.auto_saved': 'Auto-saved: ',
        'task.error_complete': 'Error completing task',
        'task.error_complete_retry': 'Error completing task. Please try again.',

        // Settings
        'settings.title': 'Settings',
        'settings.provider': 'Provider',
        'settings.provider_campuski': 'CampusKI',
        'settings.provider_openai': 'OpenAI',
        'settings.provider_custom': 'Custom',
        'settings.base_url': 'API Base URL',
        'settings.base_url_placeholder': 'https://...',
        'settings.base_url_invalid': 'Base URL must start with https://',
        'settings.api_key': 'API Key',
        'settings.api_key_placeholder': 'Enter your API key...',
        'settings.save_key': 'Save',
        'settings.model': 'Model',
        'settings.model_placeholder': 'Save API key first...',
        'settings.model_loading': 'Loading models...',
        'settings.model_error': 'Could not load models. Check your API key.',
        'settings.close': 'Close',
        'settings.no_key': 'Please enter an API key first.',
        'settings.key_saved': 'API key saved.',
        'settings.no_key_warning': '\u26a0\ufe0f Please configure your API key in Settings before starting a task.',
        'settings.dark_mode': 'Dark Mode',

        // Navigation
        'nav.admin': 'Admin',
        'nav.stats': 'Statistics',
        'nav.studies': 'Studies',
        'nav.notifications_title': 'Notifications',
        'nav.logout': 'Logout',
        'nav.login': 'Login',
        'nav.register': 'Register',

        // Feedback
        'feedback.report': 'Report Issue',
        'feedback.title': 'Report an Issue',
        'feedback.intro': 'Found a bug or have a suggestion? Let us know!',
        'feedback.category_label': 'Category',
        'feedback.cat_placeholder': '-- Please select --',
        'feedback.message_label': 'Description',
        'feedback.message_placeholder': 'Describe the problem or your suggestion...',
        'feedback.cancel': 'Cancel',
        'feedback.close': 'Close',
        'feedback.submit': 'Send',
        'feedback.success': '\u2713 Thank you! Your feedback has been sent.',
        'feedback.err_category': 'Please select a category.',
        'feedback.err_message': 'Please describe the problem.',
        'feedback.err_network': 'Network error. Please try again.',
        // Feedback categories
        'feedback.cat_bug': '\uD83D\uDC1B Bug',
        'feedback.cat_technical': '\u26A0\uFE0F Technical Problem',
        'feedback.cat_suggestion': '\uD83D\uDCA1 Suggestion',
        'feedback.cat_unclear': '\u2753 Unclear / Comprehension issue',
        'feedback.cat_general': '\uD83D\uDCAC General Feedback',
        // Maintenance
        'maintenance.title': 'Maintenance',
        'maintenance.message': 'The system is currently in maintenance mode. Please try again later.',
        // Study
        'study.done_title': 'Study completed!',
        'study.done_sub': 'You have successfully completed the study. Thank you for your participation.',
        'study.go_home': 'Back to Home',
        'study.steps_count': '{n} step(s)',
        'study.one_time_only': 'Can only be done once',
        'study.enrollment_until': 'Registration until {date}',
        'study.enrollment_from': 'from {date}',
        'study.max_participants': 'Max. {n} participants',
        'study.guided_steps': 'You will be guided through all steps without returning to the home page.',
        'study.consent_label': 'Privacy & Consent',
        'study.consent_agree': 'I have read the privacy notice and consent to the processing of my data for this study.',
        'study.enroll_btn': 'Register now & start',
        'study.cancel': 'Cancel',
        'study.list_heading': 'Research Studies',
        'study.no_studies': 'No studies currently available.',
        'study.dropped_out': 'You left this study.',
        'study.completed_on': 'Completed',
        'study.completed_badge': 'Completed',
        'study.step_progress': '{current}/{total} steps',
        'study.phases': 'Phases:',
        'study.general_wave': 'General',
        'study.continue_btn': 'Continue \u2192',
        'study.leave_btn': 'Leave study',
        'study.leave_reason_placeholder': 'Reason (optional)...',
        'study.leave_confirm': 'Really leave the study? Your progress will be saved.',
        'study.leave_yes': 'Yes, leave study',
        'study.enroll_btn_list': 'Register & Start',
        'study.waiting_title': 'Not yet available',
        'study.waiting_msg': 'The next step is not yet unlocked.',
        'study.available_from': 'Available from: {date}',
        'study.waiting_email': 'You will be notified by email when new tasks are ready for you.',
        // Survey
        'survey.page_progress': 'Page {current} of {total}',
        'survey.pct_done': '{pct}% completed',
        'survey.no_image': 'No image configured.',
        'survey.select_placeholder': '\u2014 Please select \u2014',
        'survey.prev_btn': 'Back',
        'survey.skip_btn': 'Skip',
        'survey.next_btn': 'Next',
        'survey.finish_btn': 'Submit',
        'survey.likert_min_default': 'Strongly disagree',
        'survey.likert_max_default': 'Strongly agree',
        // Task timer modal
        'task.timer_title': 'Time is up',
        'task.timer_msg': 'Your time is up. The task will now be submitted automatically.',
        // Auth
        'auth.login_page_title': 'Login',
        'auth.login_subtitle': 'Sign in to continue',
        'auth.identifier_label': 'Email or Username',
        'auth.remember_me': 'Stay logged in',
        'auth.forgot_password_link': 'Forgot password?',
        'auth.login_btn': 'Sign in',
        'auth.no_account': 'No account yet?',
        'auth.register_now': 'Register now',
        'auth.back_to_login': 'Back to Login',
        // Socket / AI errors
        'error.auth': 'Invalid or expired API key. Please check your settings.',
        'error.timeout': 'Request timed out. The AI service may be overloaded.',
        'error.connection': 'Cannot connect to the AI service. Please check your internet connection.',
        'error.rate_limit': 'Rate limit exceeded. Please wait a moment and try again.',
        'error.service_down': 'The AI service is temporarily unavailable. Please try again later.',
        'error.unexpected': 'An unexpected error occurred.',
    },
    de: {
        // Hauptseite
        'index.subtitle': 'BPMN-Modellierung Lernumgebung',
        'index.learning_path': 'Lernpfad',
        'index.select_task': 'Aufgabe ausw\u00e4hlen',
        'index.custom_title': '\u270d\ufe0f Eigene Aufgabe',
        'index.custom_desc': 'Definiere deinen eigenen Prozess. Beschreibe ihn oder lade ein Dokument (TXT, PDF, DOCX) hoch \u2014 dann modelliere ihn selbst mit Unterst\u00fctzung des Mentors.',
        'index.start_custom': 'Starten \u2192',
        'index.start_task': 'Starten \u2192',
        'index.continue_task': 'Weiter \u2192',

        // Aufgabenseite \u2014 Seitenleiste
        'task.back': '\u2190 Zur\u00fcck',
        'task.your_task': 'Deine Aufgabe',
        'task.describe_placeholder': 'Beschreibe deinen Prozess hier...',
        'task.upload_doc': '\ud83d\udcce Dokument hochladen',
        'task.confirm_start': '\u2713 Best\u00e4tigen & Starten',
        'task.export': '\ud83d\udce5 BPMN exportieren',
        'task.submit': 'Aufgabe abschlie\u00dfen',

        // Aufgabenseite \u2014 Chat
        'task.mentor': '\ud83c\udf93 Mentor',
        'task.chat_placeholder': 'Frage den Mentor um Hilfe...',
        'chat.you': 'Du',
        'chat.mentor': 'Mentor',
        'chat.resumed': 'Willkommen zurück! Dein Fortschritt wurde wiederhergestellt.',
        'chat.connection_lost': '\u26a0\ufe0f Verbindung zum Server verloren. Bitte lade die Seite neu.',

        // Abschluss-Dialog
        'task.submit_confirm_title': 'Aufgabe abschlie\u00dfen?',
        'task.submit_confirm_msg': 'Dein Modell hat noch Syntax- oder Semantikfehler. M\u00f6chtest du die Aufgabe trotzdem abschlie\u00dfen?',
        'task.cancel': 'Zur\u00fcck',
        'task.submit_btn': 'Abschlie\u00dfen',
        'task.request_review': 'Abschluss beantragen',
        'task.request_completion': 'Abschluss anfragen',
        'task.approve': 'Zustimmen',
        'task.decline': 'Ablehnen',
        'chat.colleague_proposes_completion': 'Ich denke, wir sind fertig! Sollen wir die Aufgabe abschlie\u00dfen?',
        'chat.decline_reason_prompt': 'Warum m\u00f6chtest du weitermachen? (optional)',
        'chat.decline_default': 'Lass uns noch weiter am Modell arbeiten.',

        // Probleme
        'issues.title': 'Analyseergebnisse',
        'issues.syntax': 'Syntax',
        'issues.semantic': 'Semantik',
        'issues.best_practice': 'Best Practice',
        'issues.syntax_error': 'Syntaxfehler',
        'issues.semantic_issue': 'Semantikfehler',
        'issues.dismiss': 'Verwerfen',
        'issues.element': 'Element:',
        'issues.category': 'Kategorie:',
        'issues.detected': 'Problem erkannt',
        'issues.no_details': 'Keine weiteren Details verf\u00fcgbar.',

        // Eigene Aufgabe
        'custom.no_desc': 'Bitte gib eine Aufgabenbeschreibung ein oder lade ein Dokument hoch.',
        'custom.title': 'Eigene Aufgabe',
        'custom.file_error': 'Datei konnte nicht hochgeladen werden.',
        'custom.file_read_error': 'Fehler beim Lesen der Datei',

        // Automatisches Speichern & Aufgabenabschluss
        'task.auto_saved': 'Automatisch gespeichert: ',
        'task.error_complete': 'Fehler beim Abschließen der Aufgabe',
        'task.error_complete_retry': 'Fehler beim Abschließen der Aufgabe. Bitte erneut versuchen.',

        // Einstellungen
        'settings.title': 'Einstellungen',
        'settings.provider': 'Anbieter',
        'settings.provider_campuski': 'CampusKI',
        'settings.provider_openai': 'OpenAI',
        'settings.provider_custom': 'Benutzerdefiniert',
        'settings.base_url': 'API-Basis-URL',
        'settings.base_url_placeholder': 'https://...',
        'settings.base_url_invalid': 'Basis-URL muss mit https:// beginnen',
        'settings.api_key': 'API-Schl\u00fcssel',
        'settings.api_key_placeholder': 'API-Schl\u00fcssel eingeben...',
        'settings.save_key': 'Speichern',
        'settings.model': 'Modell',
        'settings.model_placeholder': 'Erst API-Schl\u00fcssel speichern...',
        'settings.model_loading': 'Modelle werden geladen...',
        'settings.model_error': 'Modelle konnten nicht geladen werden. Pr\u00fcfe deinen API-Schl\u00fcssel.',
        'settings.close': 'Schlie\u00dfen',
        'settings.no_key': 'Bitte gib zuerst einen API-Schl\u00fcssel ein.',
        'settings.key_saved': 'API-Schl\u00fcssel gespeichert.',
        'settings.no_key_warning': '\u26a0\ufe0f Bitte konfiguriere deinen API-Schl\u00fcssel in den Einstellungen, bevor du eine Aufgabe startest.',
        'settings.dark_mode': 'Dunkelmodus',

        // Navigation
        'nav.admin': 'Admin',
        'nav.stats': 'Statistik',
        'nav.studies': 'Studien',
        'nav.notifications_title': 'Benachrichtigungen',
        'nav.logout': 'Abmelden',
        'nav.login': 'Anmelden',
        'nav.register': 'Registrieren',

        // Feedback
        'feedback.report': 'Fehler melden',
        'feedback.title': 'Problem melden',
        'feedback.intro': 'Hast du einen Fehler gefunden oder einen Verbesserungsvorschlag? Lass es uns wissen!',
        'feedback.category_label': 'Kategorie',
        'feedback.cat_placeholder': '-- Bitte w\u00e4hlen --',
        'feedback.message_label': 'Beschreibung',
        'feedback.message_placeholder': 'Beschreibe das Problem oder deinen Vorschlag...',
        'feedback.cancel': 'Abbrechen',
        'feedback.close': 'Schlie\u00dfen',
        'feedback.submit': 'Absenden',
        'feedback.success': '\u2713 Danke! Dein Feedback wurde gesendet.',
        'feedback.err_category': 'Bitte w\u00e4hle eine Kategorie.',
        'feedback.err_message': 'Bitte beschreibe das Problem.',
        'feedback.err_network': 'Netzwerkfehler. Bitte erneut versuchen.',
        // Feedback-Kategorien
        'feedback.cat_bug': '\uD83D\uDC1B Fehler / Bug',
        'feedback.cat_technical': '\u26A0\uFE0F Technisches Problem',
        'feedback.cat_suggestion': '\uD83D\uDCA1 Verbesserungsvorschlag',
        'feedback.cat_unclear': '\u2753 Unklarheit / Verst\u00e4ndnisproblem',
        'feedback.cat_general': '\uD83D\uDCAC Allgemeines Feedback',
        // Wartung
        'maintenance.title': 'Wartungsarbeiten',
        'maintenance.message': 'Das System befindet sich derzeit im Wartungsmodus. Bitte versuche es sp\u00e4ter erneut.',
        // Studie
        'study.done_title': 'Studie abgeschlossen!',
        'study.done_sub': 'Du hast die Studie erfolgreich abgeschlossen. Vielen Dank f\u00fcr deine Teilnahme.',
        'study.go_home': 'Zur Startseite',
        'study.steps_count': '{n} Schritte',
        'study.one_time_only': 'Nur einmal durchf\u00fchrbar',
        'study.enrollment_until': 'Anmeldung bis {date}',
        'study.enrollment_from': 'ab {date}',
        'study.max_participants': 'Max. {n} Teilnehmer',
        'study.guided_steps': 'Du wirst durch alle Schritte geleitet, ohne zur Startseite zur\u00fcckzukehren.',
        'study.consent_label': 'Datenschutz & Einwilligung',
        'study.consent_agree': 'Ich habe die Datenschutzhinweise gelesen und stimme der Verarbeitung meiner Daten zu dieser Studie zu.',
        'study.enroll_btn': 'Jetzt anmelden & starten',
        'study.cancel': 'Abbrechen',
        'study.list_heading': 'Research Studies',
        'study.no_studies': 'Derzeit sind keine Studies verf\u00fcgbar.',
        'study.dropped_out': 'Du hast dich aus dieser Studie abgemeldet.',
        'study.completed_on': 'Abgeschlossen',
        'study.completed_badge': 'Abgeschlossen',
        'study.step_progress': '{current}/{total} Schritte',
        'study.phases': 'Phasen:',
        'study.general_wave': 'Allgemein',
        'study.continue_btn': 'Weiter \u2192',
        'study.leave_btn': 'Studie verlassen',
        'study.leave_reason_placeholder': 'Grund (optional)...',
        'study.leave_confirm': 'Wirklich aus der Studie austreten? Dein Fortschritt bleibt gespeichert.',
        'study.leave_yes': 'Ja, Studie verlassen',
        'study.enroll_btn_list': 'Anmelden & Starten',
        'study.waiting_title': 'Noch nicht verf\u00fcgbar',
        'study.waiting_msg': 'Der n\u00e4chste Schritt ist noch nicht freigeschaltet.',
        'study.available_from': 'Verf\u00fcgbar ab: {date}',
        'study.waiting_email': 'Du wirst per E-Mail benachrichtigt, sobald neue Aufgaben f\u00fcr dich bereit sind.',
        // Umfrage
        'survey.page_progress': 'Seite {current} von {total}',
        'survey.pct_done': '{pct}% abgeschlossen',
        'survey.no_image': 'Kein Bild konfiguriert.',
        'survey.select_placeholder': '\u2014 Bitte w\u00e4hlen \u2014',
        'survey.prev_btn': 'Zur\u00fcck',
        'survey.skip_btn': '\u00dcberspringen',
        'survey.next_btn': 'Weiter',
        'survey.finish_btn': 'Abschlie\u00dfen',
        'survey.likert_min_default': 'Stimme gar nicht zu',
        'survey.likert_max_default': 'Stimme voll zu',
        // Aufgaben-Timer
        'task.timer_title': 'Zeit abgelaufen',
        'task.timer_msg': 'Deine Zeit ist abgelaufen. Die Aufgabe wird jetzt automatisch eingereicht.',
        // Anmeldung
        'auth.login_page_title': 'Anmelden',
        'auth.login_subtitle': 'Melde dich an, um fortzufahren',
        'auth.identifier_label': 'E-Mail oder Benutzername',
        'auth.remember_me': 'Angemeldet bleiben',
        'auth.forgot_password_link': 'Passwort vergessen?',
        'auth.login_btn': 'Anmelden',
        'auth.no_account': 'Noch kein Konto?',
        'auth.register_now': 'Jetzt registrieren',
        'auth.back_to_login': 'Zur\u00fcck zum Login',
        // KI-Fehler
        'error.auth': 'Ung\u00fcltiger oder abgelaufener API-Schl\u00fcssel. Bitte \u00fcberpr\u00fcfe deine Einstellungen.',
        'error.timeout': 'Zeit\u00fcberschreitung. Der KI-Dienst ist m\u00f6glicherweise \u00fcberlastet.',
        'error.connection': 'Verbindung zum KI-Dienst nicht m\u00f6glich. Bitte \u00fcberpr\u00fcfe deine Internetverbindung.',
        'error.rate_limit': 'Rate-Limit \u00fcberschritten. Bitte warte einen Moment und versuche es erneut.',
        'error.service_down': 'Der KI-Dienst ist vor\u00fcbergehend nicht verf\u00fcgbar. Bitte versuche es sp\u00e4ter erneut.',
        'error.unexpected': 'Ein unerwarteter Fehler ist aufgetreten.',
    }
};

let currentLanguage = localStorage.getItem('bpm-tutor-lang') || 'en';

/** Get translated string by key. */
function t(key) {
    const lang = TRANSLATIONS[currentLanguage] || TRANSLATIONS['en'];
    return lang[key] || TRANSLATIONS['en'][key] || key;
}

/** Switch language and re-apply all translations. */
function setLanguage(lang) {
    currentLanguage = lang;
    localStorage.setItem('bpm-tutor-lang', lang);
    document.documentElement.lang = lang;
    applyTranslations();
}

function getLanguage() {
    return currentLanguage;
}

/** Scan all [data-i18n] elements and apply translations. */
function applyTranslations() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        const translated = t(key);
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            el.placeholder = translated;
        } else {
            el.innerHTML = translated;
        }
    });

    // Translate title attributes via data-i18n-title
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        el.title = t(el.getAttribute('data-i18n-title'));
    });

    // Toggle lang-en / lang-de visibility
    document.querySelectorAll('.lang-en').forEach(el => {
        el.style.display = currentLanguage === 'en' ? '' : 'none';
    });
    document.querySelectorAll('.lang-de').forEach(el => {
        el.style.display = currentLanguage === 'de' ? '' : 'none';
    });

    // Update dropdown display
    document.querySelectorAll('.lang-current').forEach(el => {
        el.innerHTML = currentLanguage === 'de' ? FLAG_DE + ' Deutsch' : FLAG_EN + ' English';
    });
}

function toggleLangDropdown(btn) {
    const menu = btn.nextElementSibling;
    if (!menu) return;
    const open = menu.classList.toggle('open');
    if (open) {
        // Close on outside click
        setTimeout(() => {
            function handleOutside(e) {
                if (!btn.parentElement.contains(e.target)) {
                    menu.classList.remove('open');
                    document.removeEventListener('click', handleOutside);
                }
            }
            document.addEventListener('click', handleOutside);
        }, 0);
    }
}

function toggleHeaderLang(btn) {
    const menu = btn.nextElementSibling;
    if (!menu) return;
    const open = menu.classList.toggle('open');
    if (open) {
        setTimeout(() => {
            function handleOutside(e) {
                if (!btn.parentElement.contains(e.target)) {
                    menu.classList.remove('open');
                    document.removeEventListener('click', handleOutside);
                }
            }
            document.addEventListener('click', handleOutside);
        }, 0);
    }
}

// Apply language on initial load
document.addEventListener('DOMContentLoaded', () => {
    document.documentElement.lang = currentLanguage;
    applyTranslations();
});
