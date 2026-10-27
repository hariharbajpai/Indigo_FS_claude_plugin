"""Planners turn a work request into a brief and tasks.

KeywordPlanner is deterministic (tests, no API key). ClaudePlanner asks the configured model
and falls back to KeywordPlanner on any problem.
"""
import json
import os
import re
from dataclasses import dataclass, field

STOP = set("""a an the and or of to for in on at by with from is are be this that these those it its we
please need needs want do does did check make get give run see all any our your their as into than
karo karna kar kya hai hain ko ki ka ke se me mein aur ya hum humko mujhe jo yeh ye wo woh liye lie
ek sab bhi kuch work request task department dept team""".split())
CANCEL = ("cancel", "stop", "skip", "drop", "don't", "dont", "do not", "instead", "ignore",
          "ruk", "rok", "mat ", "band", "nahi", "hata", "chhod", "chod", "forget")


def tokens(text):
    out = set()
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if w in STOP or len(w) < 3:
            continue
        out.add(stem(w))
    return out


def stem(w):
    for suf in ("ing", "ions", "ion", "ies", "es", "s", "ed"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def overlap(a, b):
    """Token sets match on equality or a shared prefix of 5+ letters."""
    hits = set()
    for x in a:
        for y in b:
            if x == y or (len(x) >= 5 and len(y) >= 5 and x[:5] == y[:5]):
                hits.add(x)
    return hits


@dataclass
class PlannedTask:
    title: str
    description: str
    acceptance: str
    dept: str


@dataclass
class Plan:
    summary: str
    goals: list
    tasks: list = field(default_factory=list)
    needs_department: bool = False
    question: str = None


@dataclass
class Replan:
    summary: str
    goals: list
    new_tasks: list = field(default_factory=list)
    conflicting_task_ids: list = field(default_factory=list)
    change_note: str = ""


def _clip(text, n=140):
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "..."


class Planner:
    def plan(self, text, departments):
        raise NotImplementedError

    def replan(self, text, instruction, departments, tasks):
        raise NotImplementedError


class KeywordPlanner(Planner):
    """departments: [{id, name, head_name, keywords(optional str/list)}]."""

    def match(self, text, departments):
        want = tokens(text)
        scored = []
        for d in departments:
            scope = tokens(d["name"]) | tokens(d["id"].replace("-", " "))
            kw = d.get("keywords") or ""
            scope |= tokens(" ".join(kw) if isinstance(kw, list) else kw)
            hits = overlap(want, scope)
            if hits:
                scored.append((len(hits), d, sorted(hits)))
        return sorted(scored, key=lambda s: -s[0])

    def _task(self, d, text, hits):
        return PlannedTask(
            title=f"{d['name']}: {_clip(text, 70)}",
            description=f"Handle the part of the request in scope for {d['name']} "
                        f"(matched: {', '.join(hits)}). Request: {_clip(text, 300)}",
            acceptance=f"{d['head_name']} confirms the {d['name']} part of the request is complete, "
                       "with findings and any open risks noted.",
            dept=d["id"])

    def plan(self, text, departments):
        scored = self.match(text, departments)
        if not scored:
            names = ", ".join(d["name"] for d in departments) or "none yet"
            return Plan(
                summary=f"No existing department covers this request: {_clip(text)}",
                goals=["Find the right department before any work starts"],
                needs_department=True,
                question=f"No department matches this work (current departments: {names}). "
                         "Which department should be added to handle it? Upload its PDF and "
                         "name a Vertical Head.")
        tasks = [self._task(d, text, hits) for _, d, hits in scored]
        return Plan(
            summary=_clip(text, 200),
            goals=[f"{d['name']}: deliver its part and report back" for _, d, _ in scored],
            tasks=tasks)

    def replan(self, text, instruction, departments, tasks):
        low = instruction.lower()
        cancel = any(c in low for c in CANCEL)
        inst_tokens = tokens(instruction)
        scored = self.match(instruction, departments)
        open_tasks = [t for t in tasks if t["status"] != "done"]
        conflicts = []
        if cancel:
            matched = {d["id"] for _, d, _ in scored}
            for t in open_tasks:
                if matched:
                    hit = t["dept"] in matched
                else:
                    hit = bool(overlap(inst_tokens, tokens(t["title"])))
                if hit:
                    conflicts.append(t["id"])
        have = {t["dept"] for t in tasks if t["status"] != "blocked"}
        new = []
        if not cancel:
            for _, d, hits in scored:
                if d["id"] not in have:
                    new.append(self._task(d, instruction, hits))
        note = f"Owner instruction: {_clip(instruction, 200)}"
        goals = [f"Follow Owner instruction: {_clip(instruction, 120)}"]
        return Replan(summary=f"{_clip(text, 120)} (updated by Owner instruction)", goals=goals,
                      new_tasks=new, conflicting_task_ids=conflicts, change_note=note)


class ClaudePlanner(Planner):
    """Claude-backed planner. Needs ANTHROPIC_API_KEY and the `anthropic` package; else falls back."""

    def __init__(self, model=None, fallback=None, client=None):
        self.model = model or os.environ.get("FSA_MODEL", "claude-sonnet-4-5")
        self.fallback = fallback or KeywordPlanner()
        self._client = client

    def available(self):
        return self._client is not None or bool(os.environ.get("ANTHROPIC_API_KEY"))

    def _ask(self, prompt):
        client = self._client
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        msg = client.messages.create(model=self.model, max_tokens=1500,
                                     messages=[{"role": "user", "content": prompt}])
        text = "".join(getattr(b, "text", "") for b in msg.content)
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0))

    def plan(self, text, departments):
        if not self.available():
            return self.fallback.plan(text, departments)
        try:
            deps = [{"id": d["id"], "name": d["name"]} for d in departments]
            data = self._ask(
                "You are the Chief of Flight Safety. Plan this work request (English or Hinglish). "
                f"Departments: {json.dumps(deps)}. Request: {text}\n"
                'Reply JSON only: {"summary":str,"goals":[str],"needs_department":bool,"question":str|null,'
                '"tasks":[{"title":str,"description":str,"acceptance":str,"dept":<department id>}]}. '
                "Use only listed department ids, one department per task. If none fits set "
                "needs_department true, no tasks, and ask which department to add.")
            ids = {d["id"] for d in departments}
            tasks = [PlannedTask(t["title"], t.get("description", ""), t.get("acceptance", ""), t["dept"])
                     for t in data.get("tasks", []) if t.get("dept") in ids]
            if not tasks and not data.get("needs_department"):
                raise ValueError("no usable tasks")
            return Plan(data["summary"], list(data.get("goals", [])), tasks,
                        bool(data.get("needs_department")) and not tasks, data.get("question"))
        except Exception:
            return self.fallback.plan(text, departments)

    def replan(self, text, instruction, departments, tasks):
        if not self.available():
            return self.fallback.replan(text, instruction, departments, tasks)
        try:
            deps = [{"id": d["id"], "name": d["name"]} for d in departments]
            tl = [{"id": t["id"], "title": t["title"], "status": t["status"], "dept": t["dept"]} for t in tasks]
            data = self._ask(
                f"Chief of Flight Safety re-plan. Request: {text}\nOwner instruction: {instruction}\n"
                f"Departments: {json.dumps(deps)}\nTasks: {json.dumps(tl)}\n"
                'Reply JSON only: {"summary":str,"goals":[str],"change_note":str,"conflicting_task_ids":[str],'
                '"new_tasks":[{"title":str,"description":str,"acceptance":str,"dept":<department id>}]}')
            ids = {d["id"] for d in departments}
            tids = {t["id"] for t in tasks}
            return Replan(data["summary"], list(data.get("goals", [])),
                          [PlannedTask(t["title"], t.get("description", ""), t.get("acceptance", ""), t["dept"])
                           for t in data.get("new_tasks", []) if t.get("dept") in ids],
                          [i for i in data.get("conflicting_task_ids", []) if i in tids],
                          data.get("change_note") or f"Owner instruction: {_clip(instruction, 200)}")
        except Exception:
            return self.fallback.replan(text, instruction, departments, tasks)


def default_planner():
    p = ClaudePlanner()
    return p if p.available() else KeywordPlanner()
