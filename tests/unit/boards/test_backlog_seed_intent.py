import pytest

from boards.backlog_seed_intent import parse_seed_intent


class TestParseSeedIntent:
    def test_matches_a_full_seed_card_exactly(self):
        title = "add top 32 tasks for shop-app repo at /srv/repos/shop-app"
        description = (
            "add to trello Backlog top 32 most relevant , most impactful tasks  "
            "for shop-app repo include: at least 10 for backend and and least 5 "
            "for frontend which is not trello."
        )
        intent = parse_seed_intent(title, description)
        assert intent is not None
        assert intent.count == 32
        assert intent.min_backend == 10
        assert intent.min_frontend == 5
        assert intent.frontend_excludes_trello is True

    @pytest.mark.parametrize(
        "title",
        [
            "add top 10 tasks to Trello Backlog for shop-app",
            "seed top 15 backlog cards for repo",
            "Please create top 5 items in the Trello Backlog",
        ],
    )
    def test_matches_varied_phrasings(self, title):
        intent = parse_seed_intent(title, "")
        assert intent is not None
        assert intent.count in (5, 10, 15)

    def test_requires_backlog_hint(self):
        intent = parse_seed_intent("research top 3 approaches to caching", "brief doc only")
        assert intent is None

    def test_rejects_unreasonable_count(self):
        assert parse_seed_intent("add top 0 tasks to Backlog", "") is None
        assert parse_seed_intent("add top 500 tasks to Backlog", "") is None

    def test_defaults_when_constraints_absent(self):
        intent = parse_seed_intent("add top 8 tasks to Backlog", "no constraints")
        assert intent is not None
        assert intent.min_backend == 0
        assert intent.min_frontend == 0
        assert intent.frontend_excludes_trello is False

    def test_none_for_generic_coding_card(self):
        assert parse_seed_intent("Fix login bug", "null pointer on submit") is None
        assert parse_seed_intent("[Backend] Claim cards before execution", "race condition") is None
