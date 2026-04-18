"""Task-level statistics tracker.

One tracker entry is created per session (keyed by socket sid).
Records: wall-clock duration, LLM interaction counts, token usage.
A Markdown report is written to data/task_stats/ when the task is completed.
"""

import os
import threading
from datetime import datetime
from typing import Dict, Any


_BASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'task_stats'
)

_lock = threading.Lock()
_state: Dict[str, Dict[str, Any]] = {}


def start_task(key: str, task_id: str, session_id: str) -> None:
    with _lock:
        if key in _state:
            return
        _state[key] = {
            'task_id': task_id,
            'session_id': session_id,
            'started_at': datetime.now(),
            'finished_at': None,
            'interactions': 0,
            'tokens_in': 0,
            'tokens_out': 0,
        }
    print(f'[TaskTracker] Started tracking task {task_id} (session {session_id})')


def record_llm_call(
    key: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    with _lock:
        if key not in _state:
            return
        s = _state[key]
        s['interactions'] += 1
        s['tokens_in'] += prompt_tokens
        s['tokens_out'] += completion_tokens


def _write_report(s: dict, bpmn_xml: str = '') -> None:
    task_id = s.get('task_id', 'unknown')
    session_id = s.get('session_id', 'unknown')
    started = s['started_at']
    finished = s.get('finished_at', datetime.now())
    duration = finished - started
    duration_str = f'{duration.total_seconds():.2f}s'

    total_in = s['tokens_in']
    total_out = s['tokens_out']
    total_tok = total_in + total_out
    total_ia = s['interactions']

    report = f"""\
# Task Report: {task_id}

**Session ID:** `{session_id}`

---

## Timing

| | |
|---|---|
| Started  | {started.strftime('%Y-%m-%d %H:%M:%S')} |
| Finished | {finished.strftime('%Y-%m-%d %H:%M:%S')} |
| Duration | {duration_str} |

---

## Mentor Interactions

| Metric | Value |
|---|---|
| Interactions | {total_ia} |
| Input Tokens | {total_in:,} |
| Output Tokens | {total_out:,} |
| Total Tokens | {total_tok:,} |
"""

    folder_name = f'{task_id}_{session_id}'
    out_dir = os.path.join(_BASE_DIR, folder_name)
    os.makedirs(out_dir, exist_ok=True)

    md_path = os.path.join(out_dir, f'{folder_name}.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f'[TaskTracker] Report saved -> {md_path}')

    if bpmn_xml:
        bpmn_path = os.path.join(out_dir, f'{folder_name}.bpmn')
        with open(bpmn_path, 'w', encoding='utf-8') as f:
            f.write(bpmn_xml)
        print(f'[TaskTracker] BPMN saved -> {bpmn_path}')


def snapshot_task(key: str, bpmn_xml: str = '') -> None:
    with _lock:
        if key not in _state:
            return
        _state[key]['finished_at'] = datetime.now()
        s = dict(_state[key])
    _write_report(s, bpmn_xml)
    print(f'[TaskTracker] Snapshot written for key {key}')


def save_task_report(key: str, bpmn_xml: str = '') -> None:
    with _lock:
        if key not in _state:
            return
        _state[key]['finished_at'] = datetime.now()
        s = _state.pop(key)
    _write_report(s, bpmn_xml)
    print(f'[TaskTracker] Final report written for key {key}')


def cleanup_task(key: str) -> None:
    with _lock:
        _state.pop(key, None)
