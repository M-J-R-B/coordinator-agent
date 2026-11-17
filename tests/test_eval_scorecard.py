import json

from evals.__main__ import main
from evals.runner import Result
from evals.scorecard import NOTES_MARKER, render_markdown, summarize, write


def res(sid, expected, actual, cost=0.02, error=None, match=True, valid=True, blocked=0):
    return Result(sid, expected, actual, expected == actual and not error, [], [], match,
                  cost, 3, valid, error, blocked)


RESULTS = [
    res("a", "release", "release"),
    res("b", "hold", "hold", blocked=2),
    res("c", "hold", "release"),
    res("d", "release", "hold", cost=None),
    res("e", "hold", None, cost=None, error="boom"),
]


def test_summary_counts():
    s = summarize(RESULTS, model="m", generated_at="2026-11-17T00:00:00Z")
    assert (s["scenarios"], s["correct"], s["false_releases"], s["false_holds"], s["errors"]) == (5, 2, 1, 1, 1)
    assert s["accuracy"] == 0.4
    assert s["runs_without_cost"] == 2
    assert abs(s["total_cost_usd"] - 0.06) < 1e-9 and abs(s["mean_cost_usd"] - 0.02) < 1e-9
    assert s["blocked_release_attempts"] == 2


def test_summary_with_no_costs_at_all_uses_none():
    s = summarize([res("a", "release", "release", cost=None)], model="m", generated_at="t")
    assert s["total_cost_usd"] is None and s["mean_cost_usd"] is None


def test_summary_of_nothing_does_not_divide_by_zero():
    s = summarize([], model="m", generated_at="t")
    assert s["scenarios"] == 0 and s["accuracy"] is None


def test_markdown_leads_with_false_releases_and_shows_model_and_date():
    md = render_markdown(summarize(RESULTS, model="claude-x", generated_at="2026-11-17T00:00:00Z"), RESULTS)
    assert "claude-x" in md and "2026-11-17" in md and "simulated" in md.lower()
    assert md.index("False releases") < md.index("| a |")
    assert "2 of 5" in md
    assert "boom" in md


def test_markdown_says_when_cost_is_missing():
    md = render_markdown(summarize(RESULTS, model="m", generated_at="t"), RESULTS)
    assert "2 runs had no cost" in md


def test_markdown_escapes_pipes_in_error_text_so_the_table_survives():
    md = render_markdown(summarize([res("x", "hold", None, error="a | b\nc")], model="m", generated_at="t"),
                         [res("x", "hold", None, error="a | b\nc")])
    row = next(line for line in md.splitlines() if line.startswith("| x |"))
    assert "a \\| b c" in row


def test_write_makes_both_files(tmp_path):
    s = summarize(RESULTS, model="m", generated_at="t")
    write(s, RESULTS, json_path=tmp_path / "r" / "scorecard.json", markdown_path=tmp_path / "SCORECARD.md")
    data = json.loads((tmp_path / "r" / "scorecard.json").read_text(encoding="utf-8"))
    assert data["summary"]["correct"] == 2 and len(data["results"]) == 5
    assert (tmp_path / "SCORECARD.md").read_text(encoding="utf-8").startswith("# ")


def test_write_keeps_text_below_the_notes_marker(tmp_path):
    path = tmp_path / "SCORECARD.md"
    s = summarize(RESULTS, model="m", generated_at="t")
    write(s, RESULTS, json_path=tmp_path / "s.json", markdown_path=path)
    path.write_text(path.read_text(encoding="utf-8") + "\nScenario c: the agent misread the port table.\n",
                    encoding="utf-8")
    write(s, RESULTS, json_path=tmp_path / "s.json", markdown_path=path)
    text = path.read_text(encoding="utf-8")
    assert text.count(NOTES_MARKER) == 1
    assert text.rstrip().endswith("Scenario c: the agent misread the port table.")


def test_cli_refuses_without_live_flag(monkeypatch, capsys):
    monkeypatch.delenv("PRECHECK_LIVE", raising=False)
    assert main([]) == 2
    assert "PRECHECK_LIVE=1" in capsys.readouterr().err


def test_cli_rejects_an_unknown_scenario_id(monkeypatch, capsys):
    monkeypatch.setenv("PRECHECK_LIVE", "1")
    assert main(["--only", "no-such-scenario"]) == 2
    assert "no-such-scenario" in capsys.readouterr().err
