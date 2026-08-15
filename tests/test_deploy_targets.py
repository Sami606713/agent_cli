"""The deploy target picker.

Five destinations are listed; one works. The table is the single source of
truth for the picker, the "coming soon" message and the docs, so they cannot
drift apart and promise something that is not there.
"""

from __future__ import annotations

import pytest

from langctl.core.deploy import catalog


class TestTheCatalogIsHonest:
    def test_exactly_one_target_is_ready(self):
        ready = [t.key for t in catalog.TARGETS if t.status == "ready"]
        assert ready == ["vps"]

    def test_every_target_states_a_cost(self):
        # The number most likely to decide the answer, and the one nobody wants
        # to discover after deploying.
        for target in catalog.TARGETS:
            assert target.cost.strip(), target.key

    def test_every_target_explains_itself(self):
        for target in catalog.TARGETS:
            assert target.summary.strip() and target.detail.strip(), target.key

    def test_keys_are_unique(self):
        keys = catalog.keys()
        assert len(keys) == len(set(keys))

    def test_the_default_is_the_one_that_works(self):
        assert catalog.is_ready(catalog.DEFAULT)

    @pytest.mark.parametrize("key", ["vps", "langsmith", "gcp", "azure", "aws"])
    def test_the_five_promised_targets_exist(self, key):
        assert catalog.get(key) is not None

    def test_an_unknown_target_is_not_invented(self):
        assert catalog.get("heroku") is None
        assert not catalog.is_ready("heroku")

    def test_aws_distinguishes_itself_from_byoc(self):
        """BYOC is an Enterprise arrangement LangChain provisions, not a target
        langctl can drive. Saying so where people will look for it."""
        assert "BYOC" in catalog.get("aws").detail

    def test_langsmith_admits_it_omits_the_ui(self):
        # It hosts the agent only; claiming otherwise would break the
        # one-platform promise the command is built on.
        detail = catalog.get("langsmith").detail.lower()
        assert "ui" in detail


class TestTheSpecRemembersTheChoice:
    def test_a_new_project_has_not_been_asked(self):
        from langctl.core.project.spec import AgentSpec

        assert AgentSpec(name="x-y").deploy.target is None

    def test_a_recorded_target_survives_a_round_trip(self):
        from langctl.core.project.spec import AgentSpec

        spec = AgentSpec.from_yaml("name: x-y\ndeploy:\n  target: gcp\n")
        assert spec.deploy.target == "gcp"
