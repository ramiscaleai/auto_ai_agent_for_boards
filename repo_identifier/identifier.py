import logging

from ai_agents import StructuredLLM

from .models import RepoEntry, RepoMatch, RepoSelection
from .registry import RepoRegistry

log = logging.getLogger(__name__)

_PROMPT_TMPL = """\
You are a repo-routing assistant. Given a task description and a list of available repos, \
pick which repo(s) should be used to implement the task. Return all that are relevant.

Task:
{task}

Available repos:
{repos}

Return the repo name(s) exactly as listed and a short rationale.
"""


class RepoIdentifier:
    def __init__(self, registry: RepoRegistry, llm: StructuredLLM) -> None:
        self._registry = registry
        self._llm = llm

    def identify(self, task_description: str) -> list[RepoEntry]:
        return list(self.identify_selection(task_description).repos)

    def identify_selection(self, task_description: str) -> RepoSelection:
        entries = self._registry.all()
        if not entries:
            log.error("RepoRegistry is empty — no repos to identify")
            return RepoSelection(repos=(), rationale="No repos registered.")
        if len(entries) == 1:
            log.info("Single repo %r — skipping LLM call", entries[0].name)
            return RepoSelection(repos=(entries[0],), rationale="Only one repo is registered.")

        prompt = _PROMPT_TMPL.format(
            task=task_description.strip(),
            repos="\n".join(e.summary() for e in entries),
        )
        match: RepoMatch = self._llm.ask(prompt, RepoMatch)
        log.info("RepoIdentifier matched %s — %s", match.names, match.rationale)
        return RepoSelection(repos=tuple(_resolve(match.names, self._registry)), rationale=match.rationale)


def _resolve(names: list[str], registry: RepoRegistry) -> list[RepoEntry]:
    result = []
    for name in names:
        entry = registry.get(name)
        if entry:
            result.append(entry)
        else:
            log.warning("LLM returned unknown repo name %r — skipping", name)
    if not result:
        fallback = registry.all()[0]
        log.warning("No valid names resolved — falling back to first repo %r", fallback.name)
        result = [fallback]
    return result
