from tracker import glossary, ui


def test_terms_are_unique_and_filled():
    terms = glossary.all_terms()
    names = [t for _, t, _, _ in terms]
    assert len(names) == len(set(names)) and len(terms) >= 40
    assert all(m.strip() and len(m) > 20 for _, _, m, _ in terms)


def test_every_app_label_is_explained():
    names = {t for _, t, _, _ in glossary.all_terms()}
    for needed in ("NAV", "Drawdown", "XIRR", "Profil risiko", "Rebalancing", "Obligasi FR", "SBN ritel", "Stress test"):
        assert needed in names


def test_search_matches_every_word_in_term_or_meaning_and_filters_by_group():
    assert any(t == "Kupon" for _, t, _, _ in glossary.search("kupon"))
    assert all(g == "Obligasi & SBN" for g, _, _, _ in glossary.search("", "Obligasi & SBN"))
    both = glossary.search("harga suku bunga")
    assert both and all("harga" in (t + m + e).lower() and "suku bunga" in (t + m + e).lower() for _, t, m, e in both)
    assert glossary.search("zzzz-tidak-ada") == []


def test_term_card_escapes_and_shows_example_and_group():
    out = ui.term_card("A <b>", "arti & makna", "contoh 1", "Dasar")
    assert "A &lt;b&gt;" in out and "arti &amp; makna" in out and "Contoh:" in out and "Dasar" in out
    assert "Contoh:" not in ui.term_card("A", "b")
