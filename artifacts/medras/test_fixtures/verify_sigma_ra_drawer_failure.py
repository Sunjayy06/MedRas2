"""Verify Sigma Research Assistant drawer failures are visible and actionable."""

from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "public/js/analysis.js").read_text(encoding="utf-8")

    assert 'typeof window.RADrawer.open !== "function"' in source
    assert 'document.querySelector(".ra-drawer.is-open")' in source
    assert "Research Assistant drawer failed to open." in source
    assert (
        "Research Assistant is unavailable. Please refresh the page or check "
        "server/static assets."
    ) in source
    assert 'status.setAttribute("role", "alert")' in source
    assert 'status.setAttribute("aria-live", "assertive")' in source
    assert "openRADrawer(raBtn)" in source
    assert 'if (typeof window.RADrawer === "undefined") return;' not in source

    print("Sigma Research Assistant drawer failure verification passed.")


if __name__ == "__main__":
    main()
