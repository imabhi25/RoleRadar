"""Search tolerance: case, accents, whitespace, hyphens and punctuation never change results; technical tokens survive."""
import pytest

from api.search_text import fold_sql, fold_text, parse_search_query
from tests.test_public_visibility import _api, _company, _insert, conn  # noqa: F401  (fixtures)


def terms(query):
    return [(t.text, t.phrase) for t in parse_search_query(query)]


def test_parsing_rules():
    assert terms("  Python,   ") == [("python", False)]
    assert terms("(python)") == [("python", False)]
    assert terms("Montréal") == terms("montreal") == terms("MONTRÉAL") == [("montreal", False)]
    assert terms("québec") == terms("quebec")
    assert terms("machine-learning") == terms("machine learning") == terms("Machine   Learning") == [("ml", False)]
    assert terms("co-op") == terms("coop") == terms("Co-Ops") == [("coop", False)]
    assert terms("full-stack") == terms("full stack") == [("fullstack", False)]
    assert terms("python - engineer") == [("python", False), ("engineer", False)]
    assert terms('"software engineer"') == [("software engineer", True)]
    assert terms('"Python," engineer') == [("python", True), ("engineer", False)]
    assert terms('"unterminated') == [("unterminated", False)]
    assert terms("") == terms("   ") == terms('""') == []


def test_technical_tokens_are_preserved():
    assert terms("C++") == [("c++", False)] and terms("c#") == [("c#", False)] and terms(".NET") == [(".net", False)]
    assert terms("Node.js") == [("node.js", False)] and terms("node.js.") == [("node.js", False)]
    assert terms("C++,") == [("c++", False)]


def test_python_fold_matches_the_sql_fold_character_for_character():
    sample = "Montréal Québec São Paulo Zürich Łódź Ñandú Crème-brûlée"
    assert fold_text(sample) == "montreal quebec sao paulo zurich lodz nandu creme brulee"
    sql = fold_sql("x")
    assert sql.startswith("translate(lower(x), '") and sql.count("', '") == 1
    # the two translate() alphabets have equal length (PostgreSQL requires a 1:1 mapping)
    from api.search_text import _ACCENT_FROM, _ACCENT_TO
    assert len(_ACCENT_FROM) == len(_ACCENT_TO)


@pytest.fixture
def board(conn):  # noqa: F811
    name, cid = _company(conn)
    rows = [
        ("ml", "Machine Learning Engineer", "Montréal, QC"),
        ("ml2", "Machine-Learning Scientist", "Toronto, ON"),
        ("qc", "Backend Engineer", "Québec City, QC"),
        ("cpp", "C++ Systems Engineer", "Toronto, ON"),
        ("csharp", "C# Developer", "Toronto, ON"),
        ("net", ".NET Developer", "Toronto, ON"),
        ("node", "Node.js Engineer", "Toronto, ON"),
        ("py", "Python Developer", "Vancouver, BC"),
        ("swe", "Software Engineer", "Ottawa, ON"),
        ("coop", "Software Developer Co-op", "Waterloo, ON"),
    ]
    with conn.cursor() as cur:
        for key, title, location in rows:
            _insert(cur, cid, name + key, days_old=1, location=location, title=title)
    return name, conn


def ids(client, name, q):
    data = client.get("/api/jobs", params={"company": name, "q": q, "limit": 100}).json()
    found = {j["job_id"][len(name):] for j in data["jobs"]}
    assert data["total"] == len(found), f"count must agree with the list for {q!r}"
    return found


def test_accents_case_whitespace_and_punctuation_do_not_change_results(board):
    name, conn = board
    with _api(conn) as client:
        assert ids(client, name, "montréal") == ids(client, name, "Montreal") == ids(client, name, "  MONTREAL  ") == {"ml"}
        # Montréal is stored as "Montréal, Quebec, Canada", so a search for the province finds it as well.
        assert ids(client, name, "québec") == ids(client, name, "quebec") == {"qc", "ml"}
        assert ids(client, name, "Python,") == ids(client, name, "python") == ids(client, name, "(python)") == ids(client, name, "Python.") == {"py"}
        assert ids(client, name, "machine-learning") == ids(client, name, "machine learning") == ids(client, name, "Machine   Learning") == {"ml", "ml2"}
        assert ids(client, name, "co-op") == ids(client, name, "coop") == {"coop"}
        assert ids(client, name, "  software    engineer ") == ids(client, name, "software engineer")


def test_quoted_searches_are_literal_phrases(board):
    name, conn = board
    with _api(conn) as client:
        assert ids(client, name, '"software engineer"') == {"swe"}
        assert ids(client, name, '"engineer software"') == set()          # the words must appear together, in order
        assert ids(client, name, 'engineer software') >= {"swe"}           # unquoted words match in any order
        assert ids(client, name, '"Python," developer') == {"py"}
        assert ids(client, name, '"unterminated') == ids(client, name, "unterminated") == set()


def test_technical_tokens_keep_their_meaning(board):
    name, conn = board
    with _api(conn) as client:
        assert ids(client, name, "C++") == {"cpp"}
        assert ids(client, name, "c#") == {"csharp"}
        assert ids(client, name, ".NET") == ids(client, name, ".net,") == {"net"}
        assert ids(client, name, "Node.js") == ids(client, name, "node.js.") == {"node"}
        assert ids(client, name, "%") == set()                              # wildcards stay literal
        assert ids(client, name, "<script>alert(1)</script>") == set()


def test_list_and_count_share_the_same_normalization_across_pages(board):
    name, conn = board
    with _api(conn) as client:
        first = client.get("/api/jobs", params={"company": name, "q": "MONTRÉAL,", "limit": 1}).json()
        clean = client.get("/api/jobs", params={"company": name, "q": "montreal", "limit": 1}).json()
        assert first["total"] == clean["total"] == 1
        assert [j["job_id"] for j in first["jobs"]] == [j["job_id"] for j in clean["jobs"]]
