/**
 * BPM-Tutor — Internationalization (i18n)
 * Supports English (en) and German (de).
 */

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
        'chat.connection_lost': '\u26a0\ufe0f Connection to server lost. Please refresh the page.',

        // Completion modal
        'task.submit_confirm_title': 'Complete Task?',
        'task.submit_confirm_msg': 'Your model still has syntax or semantic errors. Are you sure you want to complete the task?',
        'task.cancel': 'Back',
        'task.submit_btn': 'Complete',

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

        // Settings
        'settings.title': 'Settings',
        'settings.api_key': 'API Key (CampusKI)',
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
        'chat.connection_lost': '\u26a0\ufe0f Verbindung zum Server verloren. Bitte lade die Seite neu.',

        // Abschluss-Dialog
        'task.submit_confirm_title': 'Aufgabe abschlie\u00dfen?',
        'task.submit_confirm_msg': 'Dein Modell hat noch Syntax- oder Semantikfehler. M\u00f6chtest du die Aufgabe trotzdem abschlie\u00dfen?',
        'task.cancel': 'Zur\u00fcck',
        'task.submit_btn': 'Abschlie\u00dfen',

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

        // Einstellungen
        'settings.title': 'Einstellungen',
        'settings.api_key': 'API-Schl\u00fcssel (CampusKI)',
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
