"""Canned answers for tests and offline demos (MEQUIZME_LLM=fake). Never calls a model."""

from __future__ import annotations


class FakeLLM:
    name = "fake"
    model = "fake-tutor"

    def __init__(self):
        self.calls: list[str] = []
        self.key_agrees = True
        self.questions: list[dict] | None = None

    def json(self, system: str, prompt: str, schema: dict) -> dict:
        self.calls.append(prompt)
        props = schema["properties"]
        if "questions" in props:
            n = props["questions"].get("maxItems", 1)
            return {"questions": self.questions if self.questions is not None else [
                _question(i, prompt) for i in range(n)]}
        out: dict = {"keyCheck": {"agrees": self.key_agrees, "note": "C looks right to me."}}
        if "explanation" in props:
            out["explanation"] = "Because of the concept."
        if "choiceRationales" in props:
            wrong = props["choiceRationales"]["items"]["properties"]["choiceId"]["enum"]
            out["choiceRationales"] = [{"choiceId": c, "rationale": f"{c} is wrong."} for c in wrong]
        if "resources" in props:
            out["resources"] = [{"title": "Docs", "url": "https://docs.databricks.com/en/machine-learning/index.html"}]
        if "topics" in props:
            out["topics"] = ["model-development"]
        if "difficulty" in props:
            out["difficulty"] = 2
        return out

    def text(self, system: str, prompt: str) -> str:
        self.calls.append(prompt)
        if "Conversation so far" in prompt:
            return "Good question. Think about what each option optimizes."
        return "Your answer does X. **Remember:** Y."


_PROMPTS = [
    "How should a nightly job score 50 million rows with a registered model?",
    "What splits requests between two served model versions on one endpoint?",
    "Which constraint makes a Unity Catalog Delta table usable as a feature table?",
    "What does AutoML produce for each trial it runs?",
    "Which call repoints the Champion alias to a new model version?",
    "Which value should fill gaps in a heavily right-skewed income column?",
    "Why use k-fold cross-validation instead of one train/test split?",
    "In what order do StringIndexer and OneHotEncoder run on a string column?",
    "When does early stopping help during hyperparameter tuning?",
    "Which design scores Kafka events within minutes into a Delta table?",
]


def _question(i: int, prompt: str) -> dict:
    return {
        "prompt": _PROMPTS[(i + len(prompt)) % len(_PROMPTS)],
        "choices": [{"id": x, "text": f"Option {x}"} for x in "ABCD"],
        "answer": ["B"],
        "explanation": "B is right because of the concept.",
        "choiceRationales": [{"choiceId": x, "rationale": f"{x} is a common mix-up."} for x in "ACD"],
        "difficulty": 2,
        "resources": [],
    }
