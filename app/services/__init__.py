"""app/services — Core backend services for BPM-Tutor.

Sub-modules are imported on demand to avoid circular imports.
  - ai_service    : AIService — LLM calls, BPMN→LION conversion
  - session_store : Thread-safe in-memory session state (keyed by SocketIO SID)
  - task_tracker  : Per-session statistics and report generation
  - prompts       : AI mentor prompt templates
"""

