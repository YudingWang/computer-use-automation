from cuas.models.action import ActionSpec, ActionType, Locator, LocatorStrategy, RiskClass, Target
from cuas.safety.policy import PolicyEngine


def test_blocks_foreign_host() -> None:
    engine = PolicyEngine()
    decision = engine.check_url("https://evil.example/transfer")
    assert not decision.allowed
    assert decision.risk is RiskClass.BLOCKED


def test_allows_localhost() -> None:
    engine = PolicyEngine()
    assert engine.check_url("http://127.0.0.1:8765/members/1").allowed


def test_risky_confirm_requires_approval() -> None:
    engine = PolicyEngine()
    engine.config.allow_risky = False
    action = ActionSpec(
        type=ActionType.CLICK,
        target=Target(primary=Locator(strategy=LocatorStrategy.ROLE_NAME, role="button", name="Confirm Open Account")),
    )
    decision = engine.check_action(action, current_url="http://127.0.0.1:8765/")
    assert not decision.allowed
    assert decision.risk is RiskClass.RISKY


def test_risky_allowed_when_flag_set() -> None:
    engine = PolicyEngine()
    engine.config.allow_risky = True
    action = ActionSpec(
        type=ActionType.CLICK,
        target=Target(primary=Locator(strategy=LocatorStrategy.ROLE_NAME, role="button", name="Confirm Open Account")),
    )
    assert engine.check_action(action, current_url="http://127.0.0.1:8765/").allowed
