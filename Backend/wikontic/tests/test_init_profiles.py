from __future__ import annotations

from scripts.init_profiles import configured_profiles


def test_profiles_are_trimmed_and_deduplicated(monkeypatch) -> None:
    monkeypatch.setenv(
        "WIKONTIC_PROFILES",
        "en__contriever, tr__turkish_e5_large, en__contriever",
    )
    assert configured_profiles() == ["en__contriever", "tr__turkish_e5_large"]
