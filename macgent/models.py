from dataclasses import dataclass, field
from typing import Optional, Any
import time


@dataclass
class Action:
    type: str  # navigate, click_element, type_text, key_press, mouse_click, scroll, execute_js, wait, open_app, calendar_add, done, fail
    params: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""


@dataclass
class Observation:
    timestamp: float = field(default_factory=time.time)
    url: Optional[str] = None
    page_title: Optional[str] = None
    page_text: Optional[str] = None
    screenshot_description: Optional[str] = None
    screenshot_b64: Optional[str] = None
    error: Optional[str] = None


@dataclass
class Step:
    step_number: int
    observation: Observation
    action: Action
    action_result: Optional[str] = None
    action_error: Optional[str] = None


@dataclass
class AgentState:
    task: str
    steps: list[Step] = field(default_factory=list)
    max_steps: int = 30
    status: str = "running"  # running, completed, failed
