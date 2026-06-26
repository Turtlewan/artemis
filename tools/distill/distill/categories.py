from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    key: str
    display_name: str
    system_prompt: str
    user_prompt_template: str
    target_count: int
    batch_size: int = 10


_SYSTEM_PROMPT = (
    "You generate synthetic assistant training data. Use only fictional, non-sensitive details. "
    "Return the requested trace blocks and no surrounding commentary."
)

CATEGORIES: tuple[Category, ...] = (
    Category(
        key="scheduling_calendar",
        display_name="Scheduling & calendar reasoning",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt_template=(
            "Generate {k} DISTINCT synthetic scheduling tasks (indices starting at {start}). "
            "For each: produce a realistic calendar/scheduling problem, reason step-by-step "
            "(full chain of thought), then give the final answer. "
            "Wrap EACH one as <trace><task>...</task><reasoning>...</reasoning>"
            "<answer>...</answer></trace>."
        ),
        target_count=200,
    ),
    Category(
        key="email_triage",
        display_name="Email triage & urgency classification",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt_template=(
            "Generate {k} DISTINCT synthetic email triage tasks (indices starting at {start}). "
            "For each: create a realistic fictional inbox item, reason step-by-step about urgency, "
            "importance, and next action, then give the final classification or reply plan. "
            "Wrap EACH one as <trace><task>...</task><reasoning>...</reasoning>"
            "<answer>...</answer></trace>."
        ),
        target_count=200,
    ),
    Category(
        key="second_brain_qa",
        display_name="Second-brain Q&A and multi-hop synthesis",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt_template=(
            "Generate {k} DISTINCT synthetic second-brain Q&A tasks (indices starting at {start}). "
            "For each: invent fictional notes or memory snippets in the task, reason step-by-step "
            "across multiple facts, then answer with a concise synthesis. "
            "Wrap EACH one as <trace><task>...</task><reasoning>...</reasoning>"
            "<answer>...</answer></trace>."
        ),
        target_count=200,
    ),
    Category(
        key="task_project_planning",
        display_name="Task & project planning / decomposition",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt_template=(
            "Generate {k} DISTINCT synthetic task and project planning problems "
            "(indices starting at {start}). For each: describe a fictional project goal with "
            "constraints, reason step-by-step through decomposition and sequencing, then give the "
            "final plan. Wrap EACH one as <trace><task>...</task><reasoning>...</reasoning>"
            "<answer>...</answer></trace>."
        ),
        target_count=200,
    ),
    Category(
        key="voice_drafting",
        display_name="Drafting in the owner's voice",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt_template=(
            "Generate {k} DISTINCT synthetic drafting tasks (indices starting at {start}). "
            "For each: invent a fictional writing situation and a requested voice or tone, reason "
            "step-by-step about audience, intent, and constraints, then provide the final draft. "
            "Wrap EACH one as <trace><task>...</task><reasoning>...</reasoning>"
            "<answer>...</answer></trace>."
        ),
        target_count=150,
    ),
    Category(
        key="research_tool_use",
        display_name="Multi-hop research & tool-use reasoning",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt_template=(
            "Generate {k} DISTINCT synthetic multi-hop research and tool-use tasks "
            "(indices starting at {start}). For each: describe a fictional research question, "
            "reason step-by-step about which sources or tools to use and how to combine findings, "
            "then give the final answer. Wrap EACH one as <trace><task>...</task>"
            "<reasoning>...</reasoning><answer>...</answer></trace>."
        ),
        target_count=150,
    ),
)
