#!/usr/bin/env python3
"""
BPM-Tutor — Deployment seed script
====================================
Run once after the first deploy (or any time you wipe the database):

    python deploy/seed.py

Each step is idempotent — safe to re-run without duplicating data.

Steps performed:
  1. Create all database tables (flask-sqlalchemy create_all)
  2. Ensure application settings defaults exist
  3. Seed supported languages (EN, DE)
  4. Seed the 5 built-in BPMN tasks
  5. Create the default admin account (configurable via env vars)
  6. Create the 5 built-in system AI agents with all prompt defaults

Environment variables (all optional — sensible defaults are used):
  ADMIN_EMAIL    — default: admin@bpmtutor.local
  ADMIN_USERNAME — default: admin
  ADMIN_PASSWORD — default: admin1234!
  DATABASE_URL   — loaded automatically from .env / environment
"""
from __future__ import annotations

import os
import sys

# Ensure the project root is on the path when run directly.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# Seed data — tasks
# ---------------------------------------------------------------------------

_SEED_TASKS = [
    {
        "id": "task_01",
        "title": "Return Processing in Online Retail",
        "title_de": "Retourenbearbeitung im Online-Handel",
        "description": (
            "An online retailer wants to model their return process. The process begins when a "
            "customer registers a return through the customer portal. The retailer's customer portal "
            "then automatically generates a return label and sends it to the customer.\n\n"
            "The customer portal now waits for the physical return to arrive. If the return does not "
            "arrive within 14 days, the return process is automatically closed without refund.\n\n"
            "When the package arrives, a warehouse employee checks the goods for defects. If the goods "
            "are damaged or incomplete, the customer is informed and the process also ends without "
            "refund. If the goods are in perfect condition, the warehouse employee forwards the "
            "information to accounting. Accounting initiates the refund of the purchase price to the "
            "customer and sends them a confirmation of the credit, which ends the process."
        ),
        "description_de": (
            "Ein Online-H\u00e4ndler m\u00f6chte seinen Retourenprozess modellieren. Der Prozess "
            "beginnt, wenn ein Kunde eine Retoure \u00fcber das Kundenportal anmeldet. Das "
            "Kundenportal des H\u00e4ndlers erstellt daraufhin automatisch ein "
            "R\u00fccksendeetikett und sendet es an den Kunden.\n\n"
            "Das Kundenportal wartet nun auf den Eingang der physischen Retoure. Wenn die Retoure "
            "nicht innerhalb von 14 Tagen eintrifft, wird der Retourenprozess automatisch ohne "
            "Erstattung geschlossen.\n\n"
            "Wenn das Paket eintrifft, pr\u00fcft ein Lagermitarbeiter die Ware auf M\u00e4ngel. "
            "Wenn die Ware besch\u00e4digt oder unvollst\u00e4ndig ist, wird der Kunde informiert "
            "und der Prozess endet ebenfalls ohne Erstattung. Wenn die Ware in einwandfreiem Zustand "
            "ist, leitet der Lagermitarbeiter die Information an die Buchhaltung weiter. Die "
            "Buchhaltung veranlasst die R\u00fcckerstattung des Kaufpreises an den Kunden und sendet "
            "ihm eine Best\u00e4tigung der Gutschrift, womit der Prozess endet."
        ),
    },
    {
        "id": "task_02",
        "title": "Insurance Claim Processing",
        "title_de": "Bearbeitung von Versicherungsanspr\u00fcchen",
        "description": (
            "An insurance company receives a damage report from a customer. A claims handler creates "
            "the case and checks the insurance coverage. If the damage is not covered, a rejection is "
            "sent directly to the customer and the case is closed.\n\n"
            "If the damage is covered, the claims handler checks the estimated damage amount. If it is "
            "below \u20ac1,500, the case is directly approved, payment is automatically initiated, and "
            "the customer is informed.\n\n"
            "If the damage amount exceeds \u20ac1,500, an external assessor must be commissioned. The "
            "insurance sends the order to the assessor and waits for their report. If the report does "
            "not arrive within 10 business days, the case is automatically rejected due to deadline "
            "expiration. If the report arrives on time, the claims handler reviews the assessment and "
            "makes a final decision on approval or rejection. In all cases, the customer is finally "
            "informed about the decision and the process ends."
        ),
        "description_de": (
            "Eine Versicherungsgesellschaft erh\u00e4lt eine Schadensmeldung von einem Kunden. Ein "
            "Sachbearbeiter erstellt den Fall und pr\u00fcft den Versicherungsschutz. Wenn der Schaden "
            "nicht abgedeckt ist, wird direkt eine Ablehnung an den Kunden gesendet und der Fall "
            "geschlossen.\n\n"
            "Wenn der Schaden abgedeckt ist, pr\u00fcft der Sachbearbeiter die gesch\u00e4tzte "
            "Schadensh\u00f6he. Liegt diese unter 1.500\u20ac, wird der Fall direkt genehmigt, die "
            "Zahlung automatisch veranlasst und der Kunde informiert.\n\n"
            "\u00dcbersteigt die Schadensh\u00f6he 1.500\u20ac, muss ein externer Gutachter "
            "beauftragt werden. Die Versicherung sendet den Auftrag an den Gutachter und wartet auf "
            "dessen Bericht. Trifft der Bericht nicht innerhalb von 10 Werktagen ein, wird der Fall "
            "automatisch wegen Fristablauf abgelehnt. Trifft der Bericht rechtzeitig ein, pr\u00fcft "
            "der Sachbearbeiter das Gutachten und trifft eine endg\u00fcltige Entscheidung. In allen "
            "F\u00e4llen wird der Kunde abschlie\u00dfend informiert und der Prozess endet."
        ),
    },
    {
        "id": "task_03",
        "title": "Vacation Request Process",
        "title_de": "Urlaubsantragsprozess",
        "description": (
            "An employee submits a vacation request through the HR portal. The request arrives at the "
            "company's HR department. The HR portal automatically checks whether the employee has "
            "enough remaining vacation days. If not, the request is automatically rejected and the "
            "employee is informed.\n\n"
            "If enough days are available, the HR portal forwards the request for approval to the "
            "employee's direct supervisor. The HR portal now waits for feedback. The supervisor can "
            "approve or reject the request.\n\n"
            "If the supervisor does not provide feedback within 5 business days, the case is "
            "escalated: An HR manager must now make a final decision (approval or rejection). Upon "
            "approval (either by the supervisor or HR manager), the HR portal books the vacation in "
            "the system. Finally, the employee is informed about the final decision."
        ),
        "description_de": (
            "Ein Mitarbeiter reicht einen Urlaubsantrag \u00fcber das HR-Portal ein. Der Antrag geht "
            "bei der Personalabteilung des Unternehmens ein. Das HR-Portal pr\u00fcft automatisch, ob "
            "der Mitarbeiter gen\u00fcgend Resturlaubstage hat. Wenn nicht, wird der Antrag "
            "automatisch abgelehnt und der Mitarbeiter informiert.\n\n"
            "Wenn gen\u00fcgend Tage verf\u00fcgbar sind, leitet das HR-Portal den Antrag zur "
            "Genehmigung an den direkten Vorgesetzten des Mitarbeiters weiter. Das HR-Portal wartet "
            "nun auf R\u00fcckmeldung. Der Vorgesetzte kann den Antrag genehmigen oder ablehnen.\n\n"
            "Wenn der Vorgesetzte innerhalb von 5 Werktagen keine R\u00fcckmeldung gibt, wird der "
            "Fall eskaliert: Ein HR-Manager muss nun eine endg\u00fcltige Entscheidung treffen. Bei "
            "Genehmigung bucht das HR-Portal den Urlaub im System. Abschlie\u00dfend wird der "
            "Mitarbeiter \u00fcber die endg\u00fcltige Entscheidung informiert."
        ),
    },
    {
        "id": "task_04",
        "title": "Processing of building permits",
        "title_de": "Bearbeitung von Baugenehmigungen",
        "description": (
            "A citizen submits a building application to the building authority. An official at the "
            "building authority checks the application for completeness. If the documents are "
            "incomplete, the citizen is given a deadline of 14 days to submit the missing documents. "
            "If the documents are not received in time, the application is rejected.\n\n"
            "If the documents are complete (either initially or after resubmission), the building "
            "authority forwards the application to the external environmental agency for review. The "
            "building authority waits for feedback.\n\n"
            "If the environmental agency issues a negative opinion, the application is rejected. If "
            "the opinion is positive, the application is forwarded internally to a test engineer. The "
            "engineer checks the technical details. If the check is positive, the building authority "
            "issues the permit. If it is negative, the application is rejected. In either case, the "
            "citizen is informed of the result."
        ),
        "description_de": (
            "Ein B\u00fcrger reicht einen Bauantrag bei der Baubeh\u00f6rde ein. Ein Beamter der "
            "Baubeh\u00f6rde pr\u00fcft den Antrag auf Vollst\u00e4ndigkeit. Wenn die Unterlagen "
            "unvollst\u00e4ndig sind, erh\u00e4lt der B\u00fcrger eine Frist von 14 Tagen, um die "
            "fehlenden Unterlagen nachzureichen. Werden die Unterlagen nicht rechtzeitig eingereicht, "
            "wird der Antrag abgelehnt.\n\n"
            "Wenn die Unterlagen vollst\u00e4ndig sind (entweder initial oder nach Nachreichung), "
            "leitet die Baubeh\u00f6rde den Antrag zur Pr\u00fcfung an die externe Umweltbeh\u00f6rde "
            "weiter. Die Baubeh\u00f6rde wartet auf R\u00fcckmeldung.\n\n"
            "Wenn die Umweltbeh\u00f6rde eine negative Stellungnahme abgibt, wird der Antrag "
            "abgelehnt. Wenn die Stellungnahme positiv ist, wird der Antrag intern an einen "
            "Pr\u00fcfingenieur weitergeleitet. Der Ingenieur pr\u00fcft die technischen Details. "
            "Bei positiver Pr\u00fcfung erteilt die Baubeh\u00f6rde die Genehmigung. Bei negativer "
            "Pr\u00fcfung wird der Antrag abgelehnt. In beiden F\u00e4llen wird der B\u00fcrger "
            "\u00fcber das Ergebnis informiert."
        ),
    },
    {
        "id": "task_05",
        "title": "Office Supply Procurement",
        "title_de": "Beschaffung von B\u00fcromaterial",
        "description": (
            "On the first business day of each quarter, a company's system checks the inventory of "
            "office supplies. If minimum stock is not reached, the process continues; otherwise, it "
            "ends immediately.\n\n"
            "With low inventory, the administration automatically sends an order request to the "
            "standard supplier. The system waits for a response. The supplier can send a confirmation "
            "or rejection (e.g., \"not deliverable\").\n\n"
            "Upon confirmation, the process ends successfully. Upon rejection or if no response is "
            "received within 3 business days, an administration employee must manually intervene. The "
            "employee checks whether to place the order with an alternative supplier. If they decide "
            "against it, the order process is cancelled. If they decide in favor, they send the order "
            "to the alternative supplier. The process ends after the order to the alternative supplier "
            "or after cancellation."
        ),
        "description_de": (
            "Am ersten Werktag jedes Quartals pr\u00fcft das System eines Unternehmens den Bestand an "
            "B\u00fcromaterial. Wenn der Mindestbestand nicht unterschritten wird, endet der Prozess "
            "sofort; andernfalls geht er weiter.\n\n"
            "Bei niedrigem Bestand sendet die Verwaltung automatisch eine Bestellanfrage an den "
            "Standardlieferanten. Das System wartet auf eine Antwort. Der Lieferant kann eine "
            "Best\u00e4tigung oder Ablehnung senden (z.B. \u201enicht lieferbar\u201c).\n\n"
            "Bei Best\u00e4tigung endet der Prozess erfolgreich. Bei Ablehnung oder wenn innerhalb "
            "von 3 Werktagen keine Antwort eingeht, muss ein Verwaltungsmitarbeiter manuell "
            "eingreifen. Der Mitarbeiter pr\u00fcft, ob die Bestellung bei einem alternativen "
            "Lieferanten aufgegeben werden soll. Entscheidet er sich dagegen, wird der "
            "Bestellvorgang abgebrochen. Entscheidet er sich daf\u00fcr, sendet er die Bestellung an "
            "den alternativen Lieferanten. Der Prozess endet nach der Bestellung beim alternativen "
            "Lieferanten oder nach dem Abbruch."
        ),
    },
]


# ---------------------------------------------------------------------------
# Seed data — system agent specs
# ---------------------------------------------------------------------------

_AGENT_SPECS = [
    {
        'agent_type': 'mentor',
        'name': 'Mentor',
        'description': (
            'Socratic guide who helps students discover BPMN concepts through questioning. '
            'Never models BPMN directly — the student always drives the canvas. '
            'Human controls task completion.'
        ),
        'is_default': True,
        'sort_order': 0,
        'modeling_mode': 'none',
        'control_mode': 'human',
    },
    {
        'agent_type': 'assistant',
        'name': 'Assistant',
        'description': (
            'Reactive helper who answers BPMN questions directly and concisely on demand. '
            'Does not model — the student drives all canvas work. '
            'Human controls task completion.'
        ),
        'is_default': False,
        'sort_order': 1,
        'modeling_mode': 'none',
        'control_mode': 'human',
    },
    {
        'agent_type': 'colleague',
        'name': 'Colleague',
        'description': (
            'Equal partner who collaborates on BPMN modeling. '
            'Proposes a fair work split and takes on a share of the canvas work. '
            'Both student and agent must agree to complete the task.'
        ),
        'is_default': False,
        'sort_order': 2,
        'modeling_mode': 'collaborative',
        'control_mode': 'shared',
    },
    {
        'agent_type': 'supervisor',
        'name': 'Supervisor',
        'description': (
            "Quality evaluator who monitors the student's modeling and directs corrections. "
            'Does not model — evaluates and approves. '
            'Agent must approve before the task can be completed.'
        ),
        'is_default': False,
        'sort_order': 3,
        'modeling_mode': 'none',
        'control_mode': 'agent',
    },
    {
        'agent_type': 'delegant',
        'name': 'Delegant',
        'description': (
            'Expert modeler who takes full responsibility for building the BPMN model. '
            'Student reviews and provides guidance; agent does all canvas work. '
            'Human controls task completion by default.'
        ),
        'is_default': False,
        'sort_order': 4,
        'modeling_mode': 'ai_only',
        'control_mode': 'human',
    },
]


# ---------------------------------------------------------------------------
# Step functions — each is idempotent
# ---------------------------------------------------------------------------

def step_create_tables() -> None:
    """Create all database tables if they don't exist yet."""
    from app.extensions import db
    db.create_all()
    print('[seed] Tables created (or already exist).')


def step_settings_defaults() -> None:
    """Ensure application settings rows exist with their default values."""
    from app.models.settings import Settings
    Settings.ensure_defaults()
    print('[seed] Application settings defaults ensured.')


def step_languages() -> None:
    """Seed EN and DE languages (and warm the i18n cache)."""
    from app.utils.i18n_helper import seed_languages, warm_cache
    seed_languages()
    warm_cache()
    print('[seed] Languages seeded and cache warmed.')


def step_tasks() -> int:
    """Insert the 5 built-in BPMN tasks if they are missing. Returns count inserted."""
    from app.extensions import db
    from app.models.task import Task

    inserted = 0
    for raw in _SEED_TASKS:
        task_id = raw.get('id')
        if not task_id:
            continue
        if db.session.get(Task, task_id) is None:
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
        print(f'[seed] Inserted {inserted} task(s).')
    else:
        print('[seed] Tasks already exist — skipped.')
    return inserted


def step_admin() -> bool:
    """Create the default admin account if no admin exists. Returns True if created."""
    from app.extensions import db
    from app.models.user import User

    if User.query.filter_by(role='admin').first():
        print('[seed] Admin account already exists — skipped.')
        return False

    email    = os.getenv('ADMIN_EMAIL',    'admin@bpmtutor.local')
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

    print(f'[seed] Admin created: {email}')
    print('[seed] IMPORTANT: Change the admin password after first login!')
    return True


def step_system_agents() -> bool:
    """Create the 5 built-in system agents with all default prompts. Returns True if any created."""
    from app.extensions import db
    from app.models.agent import AIAgent
    from app.models.agent_prompt import AgentPrompt
    from deploy.prompts import get_system_prompt
    from deploy.prompts import get_all_defaults
    from deploy.prompts.defaults import GRADING_PROMPT

    created = False
    for spec in _AGENT_SPECS:
        atype = spec['agent_type']
        if AIAgent.query.filter_by(agent_type=atype, is_system=True).first():
            continue

        agent = AIAgent(
            name=spec['name'],
            agent_type=atype,
            description=spec['description'],
            is_system=True,
            is_default=spec['is_default'],
            sort_order=spec['sort_order'],
            modeling_mode=spec['modeling_mode'],
            control_mode=spec['control_mode'],
            can_model=(spec['modeling_mode'] != 'none'),
        )
        db.session.add(agent)
        db.session.flush()  # get agent.id before inserting prompts

        # System prompts (greeting / analysis / reaction) — EN + DE
        for pt in ('greeting', 'analysis', 'reaction'):
            for lang in ('en', 'de'):
                val = get_system_prompt(atype, pt, lang)
                if val:
                    db.session.add(AgentPrompt(
                        agent_id=agent.id, prompt_type=pt, lang=lang, content=val
                    ))

        # Interaction prompts from prompt_defaults
        for (pt, lang), content in get_all_defaults(atype).items():
            if content:
                db.session.add(AgentPrompt(
                    agent_id=agent.id, prompt_type=pt, lang=lang, content=content
                ))

        # Grading prompt (shared across all agent types)
        for lang, content in GRADING_PROMPT.items():
            if content:
                db.session.add(AgentPrompt(
                    agent_id=agent.id, prompt_type='grading', lang=lang, content=content
                ))

        created = True
        print(f'[seed] Agent "{spec["name"]}" created with prompts.')

    if created:
        db.session.commit()
    else:
        print('[seed] System agents already exist — skipped.')
    return created


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_all() -> None:
    """Run all seed steps in order inside the Flask application context."""
    from app import create_app

    app = create_app()
    with app.app_context():
        print('[seed] Starting deployment seed...')
        step_create_tables()
        step_settings_defaults()
        step_languages()
        step_tasks()
        step_admin()
        step_system_agents()
        print('[seed] Done.')


if __name__ == '__main__':
    run_all()
