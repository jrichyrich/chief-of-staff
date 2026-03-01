# tests/test_memory_store.py
from datetime import datetime

import pytest
from memory.store import MemoryStore
from memory.models import AlertRule, ContextEntry, Decision, Delegation, Fact, Location



class TestFacts:
    def test_store_and_retrieve_fact(self, memory_store):
        fact = Fact(category="personal", key="name", value="Jason", source="test")
        memory_store.store_fact(fact)
        result = memory_store.get_fact("personal", "name")
        assert result is not None
        assert result.value == "Jason"
        assert result.source == "test"
        assert result.id is not None

    def test_get_nonexistent_fact(self, memory_store):
        result = memory_store.get_fact("personal", "nonexistent")
        assert result is None

    def test_update_fact_overwrites(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        memory_store.store_fact(Fact(category="personal", key="name", value="Jay"))
        result = memory_store.get_fact("personal", "name")
        assert result.value == "Jay"

    def test_get_facts_by_category(self, memory_store):
        memory_store.store_fact(Fact(category="preference", key="color", value="blue"))
        memory_store.store_fact(Fact(category="preference", key="food", value="sushi"))
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        results = memory_store.get_facts_by_category("preference")
        assert len(results) == 2

    def test_search_facts(self, memory_store):
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        memory_store.store_fact(Fact(category="work", key="title", value="Engineer"))
        results = memory_store.search_facts("Jason")
        assert len(results) == 1
        assert results[0].key == "name"


class TestLocations:
    def test_store_and_retrieve_location(self, memory_store):
        loc = Location(name="office", address="123 Main St", latitude=37.77, longitude=-122.41)
        memory_store.store_location(loc)
        result = memory_store.get_location("office")
        assert result is not None
        assert result.address == "123 Main St"

    def test_get_nonexistent_location(self, memory_store):
        result = memory_store.get_location("nowhere")
        assert result is None

    def test_list_locations(self, memory_store):
        memory_store.store_location(Location(name="home", address="456 Oak Ave"))
        memory_store.store_location(Location(name="office", address="123 Main St"))
        results = memory_store.list_locations()
        assert len(results) == 2


class TestContext:
    def test_store_and_list_context(self, memory_store):
        memory_store.store_context(ContextEntry(
            session_id="abc123",
            topic="roadmap",
            summary="Reviewed milestones and risks",
            agent="project_manager",
        ))
        memory_store.store_context(ContextEntry(
            session_id="abc123",
            topic="hiring",
            summary="Need two backend engineers",
            agent="cto",
        ))
        results = memory_store.list_context(session_id="abc123")
        assert len(results) == 2
        assert results[0].session_id == "abc123"

    def test_search_context(self, memory_store):
        memory_store.store_context(ContextEntry(
            session_id="s1",
            topic="incident response",
            summary="Postmortem action items assigned",
            agent="incident_summarizer",
        ))
        memory_store.store_context(ContextEntry(
            session_id="s2",
            topic="weekly planning",
            summary="Focus on delivery milestones",
            agent="weekly_planner",
        ))
        results = memory_store.search_context("postmortem")
        assert len(results) == 1
        assert results[0].topic == "incident response"


class TestDecisions:
    def test_store_and_retrieve_decision(self, memory_store):
        decision = Decision(
            title="Adopt microservices",
            description="Move to microservices architecture",
            context="Monolith is hitting scale limits",
            decided_by="CTO",
            owner="Platform team",
            source="meeting",
        )
        result = memory_store.store_decision(decision)
        assert result is not None
        assert result.id is not None
        assert result.title == "Adopt microservices"
        assert result.decided_by == "CTO"
        assert result.created_at is not None

    def test_get_nonexistent_decision(self, memory_store):
        result = memory_store.get_decision(999)
        assert result is None

    def test_search_decisions_by_title(self, memory_store):
        memory_store.store_decision(Decision(title="Adopt microservices"))
        memory_store.store_decision(Decision(title="Switch to PostgreSQL"))
        results = memory_store.search_decisions("micro")
        assert len(results) == 1
        assert results[0].title == "Adopt microservices"

    def test_search_decisions_by_description(self, memory_store):
        memory_store.store_decision(Decision(title="DB Choice", description="Use PostgreSQL for analytics"))
        results = memory_store.search_decisions("PostgreSQL")
        assert len(results) == 1

    def test_search_decisions_by_tags(self, memory_store):
        memory_store.store_decision(Decision(title="Infra", tags="infrastructure,cloud"))
        results = memory_store.search_decisions("cloud")
        assert len(results) == 1

    def test_list_decisions_by_status(self, memory_store):
        memory_store.store_decision(Decision(title="Done decision", status="completed"))
        memory_store.store_decision(Decision(title="Pending decision", status="pending_execution"))
        memory_store.store_decision(Decision(title="Another pending", status="pending_execution"))
        results = memory_store.list_decisions_by_status("pending_execution")
        assert len(results) == 2

    def test_update_decision(self, memory_store):
        stored = memory_store.store_decision(Decision(title="Original", status="pending_execution"))
        updated = memory_store.update_decision(stored.id, status="completed", owner="Alice")
        assert updated.status == "completed"
        assert updated.owner == "Alice"
        assert updated.updated_at != stored.updated_at

    def test_delete_decision(self, memory_store):
        stored = memory_store.store_decision(Decision(title="To delete"))
        assert memory_store.delete_decision(stored.id) is True
        assert memory_store.get_decision(stored.id) is None

    def test_delete_nonexistent_decision(self, memory_store):
        assert memory_store.delete_decision(999) is False

    def test_update_decision_rejects_invalid_fields(self, memory_store):
        stored = memory_store.store_decision(Decision(title="Test"))
        with pytest.raises(ValueError, match="Invalid decision fields"):
            memory_store.update_decision(stored.id, **{"status": "done", "id=1; DROP TABLE decisions--": "x"})

    def test_multiple_decisions_no_unique_constraint(self, memory_store):
        memory_store.store_decision(Decision(title="Same title"))
        memory_store.store_decision(Decision(title="Same title"))
        results = memory_store.search_decisions("Same title")
        assert len(results) == 2


class TestDelegations:
    def test_store_and_retrieve_delegation(self, memory_store):
        delegation = Delegation(
            task="Write Q1 report",
            delegated_to="Alice",
            delegated_by="Jason",
            due_date="2026-02-28",
            priority="high",
        )
        result = memory_store.store_delegation(delegation)
        assert result is not None
        assert result.id is not None
        assert result.task == "Write Q1 report"
        assert result.delegated_to == "Alice"
        assert result.priority == "high"
        assert result.created_at is not None

    def test_get_nonexistent_delegation(self, memory_store):
        result = memory_store.get_delegation(999)
        assert result is None

    def test_list_delegations_all(self, memory_store):
        memory_store.store_delegation(Delegation(task="Task 1", delegated_to="Alice"))
        memory_store.store_delegation(Delegation(task="Task 2", delegated_to="Bob"))
        results = memory_store.list_delegations()
        assert len(results) == 2

    def test_list_delegations_by_status(self, memory_store):
        memory_store.store_delegation(Delegation(task="Active task", delegated_to="Alice", status="active"))
        memory_store.store_delegation(Delegation(task="Done task", delegated_to="Bob", status="completed"))
        results = memory_store.list_delegations(status="active")
        assert len(results) == 1
        assert results[0].task == "Active task"

    def test_list_delegations_by_person(self, memory_store):
        memory_store.store_delegation(Delegation(task="Task A", delegated_to="Alice"))
        memory_store.store_delegation(Delegation(task="Task B", delegated_to="Bob"))
        memory_store.store_delegation(Delegation(task="Task C", delegated_to="Alice"))
        results = memory_store.list_delegations(delegated_to="Alice")
        assert len(results) == 2

    def test_list_delegations_by_status_and_person(self, memory_store):
        memory_store.store_delegation(Delegation(task="T1", delegated_to="Alice", status="active"))
        memory_store.store_delegation(Delegation(task="T2", delegated_to="Alice", status="completed"))
        memory_store.store_delegation(Delegation(task="T3", delegated_to="Bob", status="active"))
        results = memory_store.list_delegations(status="active", delegated_to="Alice")
        assert len(results) == 1
        assert results[0].task == "T1"

    def test_list_overdue_delegations(self, memory_store):
        memory_store.store_delegation(Delegation(
            task="Overdue task", delegated_to="Alice", due_date="2020-01-01", status="active",
        ))
        memory_store.store_delegation(Delegation(
            task="Future task", delegated_to="Bob", due_date="2099-12-31", status="active",
        ))
        memory_store.store_delegation(Delegation(
            task="No due date", delegated_to="Charlie", status="active",
        ))
        memory_store.store_delegation(Delegation(
            task="Completed past", delegated_to="Dave", due_date="2020-01-01", status="completed",
        ))
        results = memory_store.list_overdue_delegations()
        assert len(results) == 1
        assert results[0].task == "Overdue task"

    def test_update_delegation(self, memory_store):
        stored = memory_store.store_delegation(Delegation(task="Original", delegated_to="Alice"))
        updated = memory_store.update_delegation(stored.id, status="completed", notes="All done")
        assert updated.status == "completed"
        assert updated.notes == "All done"
        assert updated.updated_at != stored.updated_at

    def test_delete_delegation(self, memory_store):
        stored = memory_store.store_delegation(Delegation(task="To delete", delegated_to="Alice"))
        assert memory_store.delete_delegation(stored.id) is True
        assert memory_store.get_delegation(stored.id) is None

    def test_delete_nonexistent_delegation(self, memory_store):
        assert memory_store.delete_delegation(999) is False

    def test_update_delegation_rejects_invalid_fields(self, memory_store):
        stored = memory_store.store_delegation(Delegation(task="Test", delegated_to="Alice"))
        with pytest.raises(ValueError, match="Invalid delegation fields"):
            memory_store.update_delegation(stored.id, bad_field="x")

    def test_multiple_delegations_same_task(self, memory_store):
        memory_store.store_delegation(Delegation(task="Same task", delegated_to="Alice"))
        memory_store.store_delegation(Delegation(task="Same task", delegated_to="Bob"))
        results = memory_store.list_delegations()
        assert len(results) == 2


class TestAlertRules:
    def test_store_and_retrieve_alert_rule(self, memory_store):
        rule = AlertRule(
            name="overdue_check",
            description="Check for overdue delegations",
            alert_type="stale_delegation",
            condition='{"days_overdue": 3}',
        )
        result = memory_store.store_alert_rule(rule)
        assert result is not None
        assert result.id is not None
        assert result.name == "overdue_check"
        assert result.alert_type == "stale_delegation"
        assert result.enabled is True
        assert result.created_at is not None

    def test_get_nonexistent_alert_rule(self, memory_store):
        result = memory_store.get_alert_rule(999)
        assert result is None

    def test_upsert_alert_rule(self, memory_store):
        memory_store.store_alert_rule(AlertRule(
            name="test_rule", alert_type="deadline", description="Original",
        ))
        memory_store.store_alert_rule(AlertRule(
            name="test_rule", alert_type="deadline", description="Updated",
        ))
        rules = memory_store.list_alert_rules()
        assert len(rules) == 1
        assert rules[0].description == "Updated"

    def test_list_alert_rules_all(self, memory_store):
        memory_store.store_alert_rule(AlertRule(name="rule1", alert_type="deadline", enabled=True))
        memory_store.store_alert_rule(AlertRule(name="rule2", alert_type="custom", enabled=False))
        results = memory_store.list_alert_rules()
        assert len(results) == 2

    def test_list_alert_rules_enabled_only(self, memory_store):
        memory_store.store_alert_rule(AlertRule(name="enabled_rule", alert_type="deadline", enabled=True))
        memory_store.store_alert_rule(AlertRule(name="disabled_rule", alert_type="custom", enabled=False))
        results = memory_store.list_alert_rules(enabled_only=True)
        assert len(results) == 1
        assert results[0].name == "enabled_rule"

    def test_update_alert_rule(self, memory_store):
        stored = memory_store.store_alert_rule(AlertRule(name="rule", alert_type="deadline"))
        updated = memory_store.update_alert_rule(stored.id, enabled=False, description="Now disabled")
        assert updated.enabled is False
        assert updated.description == "Now disabled"

    def test_delete_alert_rule(self, memory_store):
        stored = memory_store.store_alert_rule(AlertRule(name="to_delete", alert_type="custom"))
        assert memory_store.delete_alert_rule(stored.id) is True
        assert memory_store.get_alert_rule(stored.id) is None

    def test_delete_nonexistent_alert_rule(self, memory_store):
        assert memory_store.delete_alert_rule(999) is False

    def test_update_alert_rule_rejects_invalid_fields(self, memory_store):
        stored = memory_store.store_alert_rule(AlertRule(name="rule", alert_type="test"))
        with pytest.raises(ValueError, match="Invalid alert_rule fields"):
            memory_store.update_alert_rule(stored.id, bad_field="x")


class TestMMRRerank:
    def test_empty_results(self, memory_store):
        assert memory_store._mmr_rerank([]) == []

    def test_single_result_unchanged(self, memory_store):
        fact = Fact(id=1, category="work", key="k1", value="hello world")
        results = [(fact, 1.0)]
        reranked = memory_store._mmr_rerank(results)
        assert len(reranked) == 1
        assert reranked[0][0].id == 1

    def test_diverse_results_preserve_order(self, memory_store):
        """Completely different facts should keep relevance order."""
        f1 = Fact(id=1, category="work", key="k1", value="python programming language")
        f2 = Fact(id=2, category="work", key="k2", value="favorite color blue")
        f3 = Fact(id=3, category="work", key="k3", value="meeting at noon today")
        results = [(f1, 1.0), (f2, 0.8), (f3, 0.6)]
        reranked = memory_store._mmr_rerank(results)
        assert len(reranked) == 3
        assert reranked[0][0].id == 1
        assert reranked[1][0].id == 2
        assert reranked[2][0].id == 3

    def test_redundant_results_get_demoted(self, memory_store):
        """Near-duplicate facts should be pushed down in ranking."""
        f1 = Fact(id=1, category="work", key="k1", value="project deadline friday next week")
        f2 = Fact(id=2, category="work", key="k2", value="project deadline friday this week")
        f3 = Fact(id=3, category="work", key="k3", value="favorite restaurant downtown sushi")
        # f2 is very similar to f1; f3 is completely different
        # Scores close enough that similarity penalty flips the order
        results = [(f1, 1.0), (f2, 0.6), (f3, 0.5)]
        reranked = memory_store._mmr_rerank(results)
        assert len(reranked) == 3
        # f1 picked first (highest relevance), then f3 should be promoted over f2
        assert reranked[0][0].id == 1
        assert reranked[1][0].id == 3
        assert reranked[2][0].id == 2

    def test_top_k_limits_output(self, memory_store):
        facts = [
            (Fact(id=i, category="work", key=f"k{i}", value=f"unique value {i}"), 1.0 - i * 0.1)
            for i in range(5)
        ]
        reranked = memory_store._mmr_rerank(facts, top_k=2)
        assert len(reranked) == 2

    def test_search_facts_hybrid_diverse(self, memory_store):
        """search_facts_hybrid with diverse=True should return results."""
        memory_store.store_fact(Fact(category="work", key="project_a", value="project alpha deadline"))
        memory_store.store_fact(Fact(category="work", key="project_b", value="project beta deadline"))
        memory_store.store_fact(Fact(category="personal", key="hobby", value="likes hiking outdoors"))
        results = memory_store.search_facts_hybrid("project deadline", diverse=True)
        assert len(results) >= 2
        # All results should still be (Fact, float) tuples
        for fact, score in results:
            assert isinstance(fact, Fact)
            assert isinstance(score, float)


class TestPinnedFacts:
    def test_store_pinned_fact(self, memory_store):
        """Pinned flag should persist through store and retrieve."""
        fact = Fact(category="personal", key="name", value="Jason", pinned=True)
        stored = memory_store.store_fact(fact)
        assert stored.pinned is True
        retrieved = memory_store.get_fact("personal", "name")
        assert retrieved.pinned is True

    def test_store_unpinned_fact_default(self, memory_store):
        """Facts are unpinned by default."""
        fact = Fact(category="personal", key="name", value="Jason")
        stored = memory_store.store_fact(fact)
        assert stored.pinned is False

    def test_update_fact_to_pinned(self, memory_store):
        """Updating a fact can change its pinned status."""
        memory_store.store_fact(Fact(category="work", key="project", value="Alpha"))
        memory_store.store_fact(Fact(category="work", key="project", value="Alpha", pinned=True))
        retrieved = memory_store.get_fact("work", "project")
        assert retrieved.pinned is True

    def test_pinned_fact_bypasses_temporal_decay(self, memory_store):
        """Pinned facts should return full confidence score regardless of age."""
        from datetime import timedelta
        old_time = (datetime.now() - timedelta(days=365)).isoformat()
        # Insert a pinned fact with an old timestamp
        memory_store.conn.execute(
            """INSERT INTO facts (category, key, value, confidence, pinned, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("work", "critical", "important info", 0.9, 1, old_time, old_time),
        )
        memory_store.conn.commit()
        fact = memory_store.get_fact("work", "critical")
        assert fact.pinned is True

        scored = memory_store.rank_facts([fact], half_life_days=30.0)
        assert len(scored) == 1
        # Pinned fact should have full confidence, no decay
        assert scored[0][1] == pytest.approx(0.9)

    def test_unpinned_fact_decays(self, memory_store):
        """Unpinned facts should decay based on age."""
        from datetime import timedelta
        old_time = (datetime.now() - timedelta(days=90)).isoformat()
        memory_store.conn.execute(
            """INSERT INTO facts (category, key, value, confidence, pinned, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("work", "old_info", "stale data", 1.0, 0, old_time, old_time),
        )
        memory_store.conn.commit()
        fact = memory_store.get_fact("work", "old_info")
        assert fact.pinned is False

        scored = memory_store.rank_facts([fact], half_life_days=90.0)
        # At exactly one half-life, score should be ~0.5
        assert scored[0][1] == pytest.approx(0.5, abs=0.05)

    def test_pinned_and_unpinned_ranking(self, memory_store):
        """Pinned facts should rank higher than decayed unpinned facts."""
        from datetime import timedelta
        old_time = (datetime.now() - timedelta(days=180)).isoformat()
        now = datetime.now().isoformat()
        # Old unpinned fact
        memory_store.conn.execute(
            """INSERT INTO facts (category, key, value, confidence, pinned, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("work", "old_fact", "old data", 1.0, 0, old_time, old_time),
        )
        # Pinned fact with same confidence but also old
        memory_store.conn.execute(
            """INSERT INTO facts (category, key, value, confidence, pinned, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("work", "pinned_fact", "pinned data", 1.0, 1, old_time, old_time),
        )
        memory_store.conn.commit()
        old_fact = memory_store.get_fact("work", "old_fact")
        pinned_fact = memory_store.get_fact("work", "pinned_fact")
        scored = memory_store.rank_facts([old_fact, pinned_fact], half_life_days=90.0)
        # Pinned fact should be ranked first
        assert scored[0][0].key == "pinned_fact"
        assert scored[0][1] == 1.0  # Full confidence
        assert scored[1][1] < 1.0  # Decayed


class TestConfigurableHalfLife:
    def test_custom_half_life_changes_decay(self, memory_store):
        """Different half_life_days should produce different scores."""
        from datetime import timedelta
        old_time = (datetime.now() - timedelta(days=90)).isoformat()
        memory_store.conn.execute(
            """INSERT INTO facts (category, key, value, confidence, pinned, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("work", "fact1", "test data", 1.0, 0, old_time, old_time),
        )
        memory_store.conn.commit()
        fact = memory_store.get_fact("work", "fact1")

        # Short half-life = more decay
        scored_short = memory_store.rank_facts([fact], half_life_days=30.0)
        # Long half-life = less decay
        scored_long = memory_store.rank_facts([fact], half_life_days=365.0)

        assert scored_short[0][1] < scored_long[0][1]

    def test_search_facts_hybrid_half_life(self, memory_store):
        """search_facts_hybrid should accept half_life_days."""
        memory_store.store_fact(Fact(category="work", key="project", value="test project"))
        results = memory_store.search_facts_hybrid("project", half_life_days=30.0)
        assert len(results) >= 1
        for fact, score in results:
            assert isinstance(fact, Fact)
            assert isinstance(score, float)

    def test_search_ranked_uses_half_life(self, memory_store):
        """search_facts_ranked should pass through half_life_days."""
        from datetime import timedelta
        old_time = (datetime.now() - timedelta(days=90)).isoformat()
        memory_store.conn.execute(
            """INSERT INTO facts (category, key, value, confidence, pinned, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("work", "project", "test project", 1.0, 0, old_time, old_time),
        )
        memory_store.conn.commit()
        # Rebuild FTS index
        memory_store.conn.execute("INSERT INTO facts_fts(facts_fts) VALUES('rebuild')")
        memory_store.conn.commit()

        scored_short = memory_store.search_facts_ranked("project", half_life_days=30.0)
        scored_long = memory_store.search_facts_ranked("project", half_life_days=365.0)
        if scored_short and scored_long:
            assert scored_short[0][1] < scored_long[0][1]


class TestListFacts:
    def test_list_all_facts(self, memory_store):
        memory_store.store_fact(Fact(category="work", key="isp_team_identity", value="IAM team"))
        memory_store.store_fact(Fact(category="work", key="isp_team_secops", value="SecOps team"))
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        result = memory_store.list_facts()
        assert len(result) == 3

    def test_list_facts_by_prefix(self, memory_store):
        memory_store.store_fact(Fact(category="work", key="isp_team_identity", value="IAM team"))
        memory_store.store_fact(Fact(category="work", key="isp_team_secops", value="SecOps team"))
        memory_store.store_fact(Fact(category="work", key="okr_investment_001", value="Investment"))
        result = memory_store.list_facts(prefix="isp_team_")
        assert len(result) == 2
        assert all(f.key.startswith("isp_team_") for f in result)

    def test_list_facts_by_category(self, memory_store):
        memory_store.store_fact(Fact(category="work", key="isp_team_identity", value="IAM team"))
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        result = memory_store.list_facts(category="work")
        assert len(result) == 1
        assert result[0].category == "work"

    def test_list_facts_by_prefix_and_category(self, memory_store):
        memory_store.store_fact(Fact(category="work", key="isp_team_identity", value="IAM team"))
        memory_store.store_fact(Fact(category="personal", key="isp_note", value="note"))
        result = memory_store.list_facts(prefix="isp_", category="work")
        assert len(result) == 1
        assert result[0].key == "isp_team_identity"

    def test_list_facts_with_limit(self, memory_store):
        for i in range(5):
            memory_store.store_fact(Fact(category="work", key=f"item_{i}", value=f"val {i}"))
        result = memory_store.list_facts(limit=3)
        assert len(result) == 3

    def test_list_facts_empty(self, memory_store):
        result = memory_store.list_facts()
        assert result == []


class TestListFactKeys:
    def test_list_all_keys(self, memory_store):
        memory_store.store_fact(Fact(category="work", key="isp_team_identity", value="IAM"))
        memory_store.store_fact(Fact(category="work", key="isp_team_secops", value="SecOps"))
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        result = memory_store.list_fact_keys()
        assert len(result) == 3
        assert "isp_team_identity" in result
        assert "name" in result

    def test_list_keys_by_prefix(self, memory_store):
        memory_store.store_fact(Fact(category="work", key="isp_team_identity", value="IAM"))
        memory_store.store_fact(Fact(category="work", key="isp_team_secops", value="SecOps"))
        memory_store.store_fact(Fact(category="work", key="okr_investment_001", value="Inv"))
        result = memory_store.list_fact_keys(prefix="isp_")
        assert len(result) == 2
        assert all(k.startswith("isp_") for k in result)

    def test_list_keys_by_category(self, memory_store):
        memory_store.store_fact(Fact(category="work", key="isp_team_identity", value="IAM"))
        memory_store.store_fact(Fact(category="personal", key="name", value="Jason"))
        result = memory_store.list_fact_keys(category="work")
        assert result == ["isp_team_identity"]

    def test_list_keys_empty(self, memory_store):
        result = memory_store.list_fact_keys()
        assert result == []
