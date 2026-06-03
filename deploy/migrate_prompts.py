"""Migrate existing system agent prompts in the DB to the latest content.

Run this script after deploying updated prompt files to bring the live
database in sync with the source-of-truth values in ``deploy/prompts/``.

The script is **idempotent**: prompts whose content is already up-to-date
are left untouched.  Only inserts or updates are shown in the output.

Usage::

    # From the project root:
    python -m deploy.migrate_prompts
    # or
    python deploy/migrate_prompts.py
"""
from __future__ import annotations

import os
import sys


def run() -> None:
    from app import create_app
    from app.extensions import db
    from app.models.agent import AIAgent
    from app.models.agent_prompt import AgentPrompt
    from deploy.prompts import get_system_prompt, get_all_defaults
    from deploy.prompts.defaults import GRADING_PROMPT

    app = create_app()

    with app.app_context():
        updated = 0
        unchanged = 0

        agents: list[AIAgent] = AIAgent.query.filter_by(is_system=True).order_by(AIAgent.sort_order).all()
        if not agents:
            print('[migrate] No system agents found in the database.')
            print('[migrate] Run "python -m deploy.seed" first to create them.')
            return

        for agent in agents:
            atype = agent.agent_type
            print(f'\n[migrate] Agent: {agent.name!r}  (type={atype})')

            # ── System prompts (greeting / analysis / reaction) ───────────────
            for pt in ('greeting', 'analysis', 'reaction'):
                for lang in ('en', 'de'):
                    new_content = get_system_prompt(atype, pt, lang)
                    if not new_content:
                        continue

                    row: AgentPrompt | None = AgentPrompt.query.filter_by(
                        agent_id=agent.id, prompt_type=pt, lang=lang
                    ).first()

                    if row is None:
                        db.session.add(AgentPrompt(
                            agent_id=agent.id,
                            prompt_type=pt,
                            lang=lang,
                            content=new_content,
                        ))
                        print(f'  + created  {pt}/{lang}  ({len(new_content)} chars)')
                        updated += 1
                    elif row.content != new_content:
                        row.content = new_content
                        print(f'  ~ updated  {pt}/{lang}  ({len(new_content)} chars)')
                        updated += 1
                    else:
                        unchanged += 1

            # ── Interaction prompts ────────────────────────────────────────────
            for (pt, lang), new_content in get_all_defaults(atype).items():
                if not new_content:
                    continue

                row = AgentPrompt.query.filter_by(
                    agent_id=agent.id, prompt_type=pt, lang=lang
                ).first()

                if row is None:
                    db.session.add(AgentPrompt(
                        agent_id=agent.id,
                        prompt_type=pt,
                        lang=lang,
                        content=new_content,
                    ))
                    print(f'  + created  {pt}/{lang}  ({len(new_content)} chars)')
                    updated += 1
                elif row.content != new_content:
                    row.content = new_content
                    print(f'  ~ updated  {pt}/{lang}  ({len(new_content)} chars)')
                    updated += 1
                else:
                    unchanged += 1

            # ── Grading prompt (shared, same for every agent type) ─────────────
            for lang, new_content in GRADING_PROMPT.items():
                if not new_content:
                    continue

                row = AgentPrompt.query.filter_by(
                    agent_id=agent.id, prompt_type='grading', lang=lang
                ).first()

                if row is None:
                    db.session.add(AgentPrompt(
                        agent_id=agent.id,
                        prompt_type='grading',
                        lang=lang,
                        content=new_content,
                    ))
                    print(f'  + created  grading/{lang}  ({len(new_content)} chars)')
                    updated += 1
                elif row.content != new_content:
                    row.content = new_content
                    print(f'  ~ updated  grading/{lang}  ({len(new_content)} chars)')
                    updated += 1
                else:
                    unchanged += 1

        db.session.commit()
        print(f'\n[migrate] Done.  Updated: {updated}  |  Already up-to-date: {unchanged}')


if __name__ == '__main__':
    # Allow running directly: python deploy/migrate_prompts.py
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    run()
