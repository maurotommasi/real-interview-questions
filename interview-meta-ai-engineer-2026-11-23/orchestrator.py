"""Production agent orchestrator with safety guardrails.
Meta AI Engineer representative interview solution.
Runs with the Python standard library only.
"""
import hashlib, json, time
from dataclasses import dataclass, field

@dataclass
class Task:
    id: str
    prompt: str
    tools: list
    budget_usd: float = 0.50

@dataclass
class AuditEvent:
    ts: float
    task_id: str
    kind: str
    detail: str

class Guardrail:
    BLOCKED_TOOLS = {"disable_monitoring", "delete_logs", "shell_unrestricted"}
    PII_MARKERS = ("password", "ssn", "credit card")
    def check_tool(self, name):
        return name not in self.BLOCKED_TOOLS
    def check_prompt(self, text):
        low = text.lower()
        return not any(m in low for m in self.PII_MARKERS)

class Orchestrator:
    def __init__(self):
        self.guard = Guardrail()
        self.audit = []
        self.spent = 0.0
        self.killed = False
    def log(self, task_id, kind, detail):
        self.audit.append(AuditEvent(time.time(), task_id, kind, detail))
    def run_task(self, task, model_fn):
        if self.killed:
            self.log(task.id, "refused", "kill switch is on")
            return {"status": "refused_killed"}
        if not self.guard.check_prompt(task.prompt):
            self.log(task.id, "blocked", "sensitive marker in prompt")
            return {"status": "blocked_prompt"}
        for tool in task.tools:
            if not self.guard.check_tool(tool):
                self.log(task.id, "blocked", f"tool {tool} is not allowed")
                self.killed = True
                self.log(task.id, "kill_switch", "agent tried to disable monitoring, all work stopped")
                return {"status": "blocked_tool", "tool": tool}
        cost = 0.04 * max(1, len(task.prompt.split()) // 10)
        if self.spent + cost > task.budget_usd:
            self.log(task.id, "blocked", "budget cap reached")
            return {"status": "blocked_budget"}
        self.spent += cost
        out = model_fn(task.prompt)
        digest = hashlib.sha256(out.encode()).hexdigest()[:12]
        self.log(task.id, "completed", f"output hash {digest} cost {cost:.2f}")
        return {"status": "completed", "output": out, "cost": round(cost, 2)}
    def report(self):
        return {"spent_usd": round(self.spent, 2), "killed": self.killed,
                "audit_events": len(self.audit),
                "events": [(e.kind, e.detail) for e in self.audit]}

def fake_model(prompt):
    return "Plan: summarise the request, call the allowed search tool, draft the answer, and stop for human review before any external action. Prompt was: " + prompt[:60]

if __name__ == "__main__":
    print(json.dumps({"module": "orchestrator", "ready": True}))
