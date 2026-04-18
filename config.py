import os
from dotenv import load_dotenv

load_dotenv()

CAMPUS_KI_BASE_URL = os.getenv("CAMPUS_KI_BASE_URL", "https://chat.kiconnect.nrw/api")

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY not set in .env file")
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

AI_CONFIG = {
    "max_chat_history": 20,
}

LOG_LLM_IO = False

TASKS = [
    {
        "id": "task_01",
        "title": "Return Processing in Online Retail",
        "title_de": "Retourenbearbeitung im Online-Handel",
        "description": """An online retailer wants to model their return process. The process begins when a customer registers a return through the customer portal. The retailer's customer portal then automatically generates a return label and sends it to the customer.

The customer portal now waits for the physical return to arrive. If the return does not arrive within 14 days, the return process is automatically closed without refund.

When the package arrives, a warehouse employee checks the goods for defects. If the goods are damaged or incomplete, the customer is informed and the process also ends without refund. If the goods are in perfect condition, the warehouse employee forwards the information to accounting. Accounting initiates the refund of the purchase price to the customer and sends them a confirmation of the credit, which ends the process.""",
        "description_de": """Ein Online-H\u00e4ndler m\u00f6chte seinen Retourenprozess modellieren. Der Prozess beginnt, wenn ein Kunde eine Retoure \u00fcber das Kundenportal anmeldet. Das Kundenportal des H\u00e4ndlers erstellt daraufhin automatisch ein R\u00fccksendeetikett und sendet es an den Kunden.

Das Kundenportal wartet nun auf den Eingang der physischen Retoure. Wenn die Retoure nicht innerhalb von 14 Tagen eintrifft, wird der Retourenprozess automatisch ohne Erstattung geschlossen.

Wenn das Paket eintrifft, pr\u00fcft ein Lagermitarbeiter die Ware auf M\u00e4ngel. Wenn die Ware besch\u00e4digt oder unvollst\u00e4ndig ist, wird der Kunde informiert und der Prozess endet ebenfalls ohne Erstattung. Wenn die Ware in einwandfreiem Zustand ist, leitet der Lagermitarbeiter die Information an die Buchhaltung weiter. Die Buchhaltung veranlasst die R\u00fcckerstattung des Kaufpreises an den Kunden und sendet ihm eine Best\u00e4tigung der Gutschrift, womit der Prozess endet."""
    },
    {
        "id": "task_02",
        "title": "Insurance Claim Processing",
        "title_de": "Bearbeitung von Versicherungsanspr\u00fcchen",
        "description": """An insurance company receives a damage report from a customer. A claims handler creates the case and checks the insurance coverage. If the damage is not covered, a rejection is sent directly to the customer and the case is closed.

If the damage is covered, the claims handler checks the estimated damage amount. If it is below \u20ac1,500, the case is directly approved, payment is automatically initiated, and the customer is informed.

If the damage amount exceeds \u20ac1,500, an external assessor must be commissioned. The insurance sends the order to the assessor and waits for their report. If the report does not arrive within 10 business days, the case is automatically rejected due to deadline expiration. If the report arrives on time, the claims handler reviews the assessment and makes a final decision on approval or rejection. In all cases, the customer is finally informed about the decision (approval, rejection, or rejection due to deadline expiration) and the process ends.""",
        "description_de": """Eine Versicherungsgesellschaft erh\u00e4lt eine Schadensmeldung von einem Kunden. Ein Sachbearbeiter erstellt den Fall und pr\u00fcft den Versicherungsschutz. Wenn der Schaden nicht abgedeckt ist, wird direkt eine Ablehnung an den Kunden gesendet und der Fall geschlossen.

Wenn der Schaden abgedeckt ist, pr\u00fcft der Sachbearbeiter die gesch\u00e4tzte Schadensh\u00f6he. Liegt diese unter 1.500\u20ac, wird der Fall direkt genehmigt, die Zahlung automatisch veranlasst und der Kunde informiert.

\u00dcbersteigt die Schadensh\u00f6he 1.500\u20ac, muss ein externer Gutachter beauftragt werden. Die Versicherung sendet den Auftrag an den Gutachter und wartet auf dessen Bericht. Trifft der Bericht nicht innerhalb von 10 Werktagen ein, wird der Fall automatisch wegen Fristablauf abgelehnt. Trifft der Bericht rechtzeitig ein, pr\u00fcft der Sachbearbeiter das Gutachten und trifft eine endg\u00fcltige Entscheidung \u00fcber Genehmigung oder Ablehnung. In allen F\u00e4llen wird der Kunde abschlie\u00dfend \u00fcber die Entscheidung (Genehmigung, Ablehnung oder Ablehnung wegen Fristablauf) informiert und der Prozess endet."""
    },
    {
        "id": "task_03",
        "title": "Vacation Request Process",
        "title_de": "Urlaubsantragsprozess",
        "description": """An employee submits a vacation request through the HR portal. The request arrives at the company's HR department. The HR portal automatically checks whether the employee has enough remaining vacation days. If not, the request is automatically rejected and the employee is informed.

If enough days are available, the HR portal forwards the request for approval to the employee's direct supervisor. The HR portal now waits for feedback. The supervisor can approve or reject the request.

If the supervisor does not provide feedback within 5 business days, the case is escalated: An HR manager must now make a final decision (approval or rejection). Upon approval (either by the supervisor or HR manager), the HR portal books the vacation in the system. Finally, the employee is informed about the final decision (approval, rejection by supervisor, or rejection by HR manager).""",
        "description_de": """Ein Mitarbeiter reicht einen Urlaubsantrag \u00fcber das HR-Portal ein. Der Antrag geht bei der Personalabteilung des Unternehmens ein. Das HR-Portal pr\u00fcft automatisch, ob der Mitarbeiter gen\u00fcgend Resturlaubstage hat. Wenn nicht, wird der Antrag automatisch abgelehnt und der Mitarbeiter informiert.

Wenn gen\u00fcgend Tage verf\u00fcgbar sind, leitet das HR-Portal den Antrag zur Genehmigung an den direkten Vorgesetzten des Mitarbeiters weiter. Das HR-Portal wartet nun auf R\u00fcckmeldung. Der Vorgesetzte kann den Antrag genehmigen oder ablehnen.

Wenn der Vorgesetzte innerhalb von 5 Werktagen keine R\u00fcckmeldung gibt, wird der Fall eskaliert: Ein HR-Manager muss nun eine endg\u00fcltige Entscheidung (Genehmigung oder Ablehnung) treffen. Bei Genehmigung (entweder durch den Vorgesetzten oder den HR-Manager) bucht das HR-Portal den Urlaub im System. Abschlie\u00dfend wird der Mitarbeiter \u00fcber die endg\u00fcltige Entscheidung informiert (Genehmigung, Ablehnung durch Vorgesetzten oder Ablehnung durch HR-Manager)."""
    },
    {
        "id": "task_04",
        "title": "Processing of building permits",
        "title_de": "Bearbeitung von Baugenehmigungen",
        "description": """A citizen submits a building application to the building authority. An official at the building authority checks the application for completeness. If the documents are incomplete, the citizen is given a deadline of 14 days to submit the missing documents. If the documents are not received in time, the application is rejected.

If the documents are complete (either initially or after resubmission), the building authority forwards the application to the external environmental agency for review. The building authority waits for feedback.

If the environmental agency issues a negative opinion, the application is rejected. If the opinion is positive, the application is forwarded internally to a test engineer. The engineer checks the technical details. If the check is positive, the building authority issues the permit. If it is negative, the application is rejected. In either case (approval or rejection), the citizen is informed of the result.""",
        "description_de": """Ein B\u00fcrger reicht einen Bauantrag bei der Baubeh\u00f6rde ein. Ein Beamter der Baubeh\u00f6rde pr\u00fcft den Antrag auf Vollst\u00e4ndigkeit. Wenn die Unterlagen unvollst\u00e4ndig sind, erh\u00e4lt der B\u00fcrger eine Frist von 14 Tagen, um die fehlenden Unterlagen nachzureichen. Werden die Unterlagen nicht rechtzeitig eingereicht, wird der Antrag abgelehnt.

Wenn die Unterlagen vollst\u00e4ndig sind (entweder initial oder nach Nachreichung), leitet die Baubeh\u00f6rde den Antrag zur Pr\u00fcfung an die externe Umweltbeh\u00f6rde weiter. Die Baubeh\u00f6rde wartet auf R\u00fcckmeldung.

Wenn die Umweltbeh\u00f6rde eine negative Stellungnahme abgibt, wird der Antrag abgelehnt. Wenn die Stellungnahme positiv ist, wird der Antrag intern an einen Pr\u00fcfingenieur weitergeleitet. Der Ingenieur pr\u00fcft die technischen Details. Bei positiver Pr\u00fcfung erteilt die Baubeh\u00f6rde die Genehmigung. Bei negativer Pr\u00fcfung wird der Antrag abgelehnt. In beiden F\u00e4llen (Genehmigung oder Ablehnung) wird der B\u00fcrger \u00fcber das Ergebnis informiert."""
    },
    {
        "id": "task_05",
        "title": "Office Supply Procurement",
        "title_de": "Beschaffung von B\u00fcromaterial",
        "description": """On the first business day of each quarter, a company's system checks the inventory of office supplies. If minimum stock is not reached, the process continues; otherwise, it ends immediately.

With low inventory, the administration automatically sends an order request to the standard supplier. The system waits for a response. The supplier can send a confirmation or rejection (e.g., "not deliverable").

Upon confirmation, the process ends successfully. Upon rejection or if no response is received within 3 business days, an administration employee must manually intervene. The employee checks whether to place the order with an alternative supplier. If they decide against it (e.g., too expensive), the order process is cancelled. If they decide in favor, they send the order to the alternative supplier. The process ends after the order to the alternative supplier or after cancellation.""",
        "description_de": """Am ersten Werktag jedes Quartals pr\u00fcft das System eines Unternehmens den Bestand an B\u00fcromaterial. Wenn der Mindestbestand nicht unterschritten wird, endet der Prozess sofort; andernfalls geht er weiter.

Bei niedrigem Bestand sendet die Verwaltung automatisch eine Bestellanfrage an den Standardlieferanten. Das System wartet auf eine Antwort. Der Lieferant kann eine Best\u00e4tigung oder Ablehnung senden (z.B. \u201enicht lieferbar\u201c).

Bei Best\u00e4tigung endet der Prozess erfolgreich. Bei Ablehnung oder wenn innerhalb von 3 Werktagen keine Antwort eingeht, muss ein Verwaltungsmitarbeiter manuell eingreifen. Der Mitarbeiter pr\u00fcft, ob die Bestellung bei einem alternativen Lieferanten aufgegeben werden soll. Entscheidet er sich dagegen (z.B. zu teuer), wird der Bestellvorgang abgebrochen. Entscheidet er sich daf\u00fcr, sendet er die Bestellung an den alternativen Lieferanten. Der Prozess endet nach der Bestellung beim alternativen Lieferanten oder nach dem Abbruch."""
    }
]

TASKS_BY_ID = {t['id']: t for t in TASKS}

# ── LION action schema mappings (moved from benchmarks) ──────────────────────
LION_SCHEMA_MAPPINGS = {
    'participate': {
        'x': 'x', 'y': 'y', 'w': 'width', 'h': 'height',
        'label': 'label', 'id': 'elementId', 'expanded': 'isExpanded',
        'lanes': 'lanes',
    },
    'draw': {
        'type': 'elementType', 'x': 'x', 'y': 'y', 'label': 'label',
        'id': 'elementId', 'parent': 'parentId', 'connectTo': 'connectTo',
        'eventDef': 'eventDefinition',
    },
    'connect': {'src': 'sourceId', 'tgt': 'targetId', 'label': 'label'},
    'rename': {'id': 'elementId', 'label': 'label'},
    'move': {'id': 'elementId', 'x': 'x', 'y': 'y'},
    'resize': {'id': 'elementId', 'w': 'width', 'h': 'height'},
    'update': {'id': 'elementId', 'prop': 'property', 'val': 'value'},
}

ACTION_ORDER = ['delete', 'resize', 'move', 'participate', 'draw', 'rename', 'update', 'connect']
