import json, sys
sys.stdout = open('prompts_dump.json', 'w', encoding='utf-8')
from app import create_app
from app.extensions import db
app = create_app()
with app.app_context():
    with db.engine.connect() as conn:
        rows = conn.execute(db.text("""
            SELECT ap.agent_id, a.agent_type, a.name,
                   ap.prompt_type, ap.lang, ap.content
            FROM agent_prompts ap
            JOIN ai_agents a ON a.id = ap.agent_id
            ORDER BY a.agent_type, ap.prompt_type, ap.lang
        """)).fetchall()
        data = [{'agent_type': r[1], 'agent_name': r[2], 'agent_id': r[0],
                 'prompt_type': r[3], 'lang': r[4], 'content': r[5]} for r in rows]
        print(json.dumps(data, ensure_ascii=False, indent=2))
sys.stdout.close()
print('done', file=sys.stderr)
