"""The SQL driver script must run under the interpreter whose SQLAlchemy the capability check found."""

import sys

import pytest

from worker import runtime


def test_sql_driver_uses_the_workers_own_interpreter_when_sqlalchemy_is_importable(monkeypatch):
    pytest.importorskip("sqlalchemy")
    monkeypatch.setattr(runtime, "_get_python_path", lambda: "")
    monkeypatch.setattr(runtime, "_find_python", lambda: "some-other-python")
    assert runtime._sql_python() == sys.executable


def test_an_explicit_python_path_still_wins(monkeypatch):
    monkeypatch.setattr(runtime, "_get_python_path", lambda: "/opt/custom/python")
    monkeypatch.setattr(runtime, "_find_python", lambda: "/opt/custom/python")
    assert runtime._sql_python() == "/opt/custom/python"


def test_without_sqlalchemy_it_falls_back_to_path_lookup(monkeypatch):
    monkeypatch.setattr(runtime, "_get_python_path", lambda: "")
    monkeypatch.setattr(runtime, "_find_python", lambda: "python-on-path")
    monkeypatch.setitem(sys.modules, "sqlalchemy", None)  # makes `import sqlalchemy` raise ImportError
    assert runtime._sql_python() == "python-on-path"
