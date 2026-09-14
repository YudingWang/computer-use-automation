import httpx


def test_member_lookup_and_not_found(demo_url: str) -> None:
    with httpx.Client(base_url=demo_url, follow_redirects=True) as client:
        found = client.get("/search", params={"member_id": "12345"})
        assert found.status_code == 200
        assert "Alice Chen" in found.text
        assert "Savings balance" in found.text
        missing = client.get("/search", params={"member_id": "99999"})
        assert "Member not found" in missing.text


def test_restricted_member(demo_url: str) -> None:
    with httpx.Client(base_url=demo_url, follow_redirects=True) as client:
        page = client.get("/members/24680/forbidden")
        assert "Permission denied" in page.text


def test_eastside_branding(demo_url: str) -> None:
    with httpx.Client(base_url=demo_url, follow_redirects=True) as client:
        page = client.get("/search-panel", params={"brand": "eastside"})
        assert "Member Number" in page.text
        assert "Find Member" in page.text
