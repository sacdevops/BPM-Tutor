"""Runtime seeder utilities — functions called from the admin UI."""
from __future__ import annotations


def reset_system_agent_prompts() -> int:
    """Overwrite all prompts of system agents with the current built-in defaults.

    Safe to call at any time. Returns the number of agents updated.
    """
    try:
        from app.extensions import db
        from app.models.agent import AIAgent
        from app.models.agent_prompt import AgentPrompt
        from deploy.prompts import get_system_prompt
        from deploy.prompts import get_all_defaults
        from deploy.prompts.defaults import GRADING_PROMPT

        count = 0
        for agent in AIAgent.query.filter_by(is_system=True).all():
            atype = agent.agent_type
            if not atype:
                continue

            # Reset system prompts (EN + DE only -- other langs stay as-is)
            for pt in ('greeting', 'analysis', 'reaction'):
                for lang in ('en', 'de'):
                    val = get_system_prompt(atype, pt, lang)
                    if val:
                        ap = AgentPrompt.query.filter_by(
                            agent_id=agent.id, prompt_type=pt, lang=lang
                        ).first()
                        if ap:
                            ap.content = val
                        else:
                            db.session.add(AgentPrompt(
                                agent_id=agent.id, prompt_type=pt, lang=lang, content=val
                            ))

            # Reset interaction prompts from prompt_defaults
            for (pt, lang), content in get_all_defaults(atype).items():
                ap = AgentPrompt.query.filter_by(
                    agent_id=agent.id, prompt_type=pt, lang=lang
                ).first()
                if ap:
                    ap.content = content
                else:
                    db.session.add(AgentPrompt(
                        agent_id=agent.id, prompt_type=pt, lang=lang, content=content
                    ))

            # Reset grading prompt
            for lang, content in GRADING_PROMPT.items():
                ap = AgentPrompt.query.filter_by(
                    agent_id=agent.id, prompt_type='grading', lang=lang
                ).first()
                if ap:
                    ap.content = content
                else:
                    db.session.add(AgentPrompt(
                        agent_id=agent.id, prompt_type='grading', lang=lang, content=content
                    ))
            count += 1

        if count:
            db.session.commit()
        return count

    except Exception as exc:
        try:
            from flask import current_app
            current_app.logger.warning('[agents] reset_system_agent_prompts failed: %s', exc)
        except Exception:
            pass
        return 0
