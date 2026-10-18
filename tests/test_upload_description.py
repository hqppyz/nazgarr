"""La sandbox dei template delle descrizioni (nazgarr/upload/description.py)."""

import time

import pytest

from nazgarr.upload.description import DescriptionTemplateError, render_template


@pytest.mark.parametrize("source", [
    "{{ (9 ** (9 ** 8)) > 0 }}",  # piegato da Jinja già alla compilazione, col GIL tenuto
    "{{ 'x' * 10 ** 10 }}",
    "{{ 10 ** 10 * 'x' }}",
    "{{ [1, 2] * 10 ** 9 }}",
    "{{ (10 ** 1000) ** 1000 }}",
    "{% set ns = namespace(n=10 ** 1000) %}{% for i in range(30) %}{% set ns.n = ns.n * ns.n %}{% endfor %}",
    "{{ 9 ** (9 ** 4) }}",  # più di 4300 cifre da scrivere: ValueError
    "{{ 1 / 0 }}",
    "{{ 2.5 ** 100000 }}",
])
def test_a_template_cannot_exhaust_the_process(source):
    """Audit 2026-10-18: la sandbox fermava il codice, non i conti."""
    started = time.monotonic()
    with pytest.raises(DescriptionTemplateError) as exc:
        render_template(source)
    assert exc.value.code == "upload_description_template_invalid"
    assert time.monotonic() - started < 2


def test_ordinary_arithmetic_and_repetition_still_work():
    assert render_template("{{ 2 ** 10 }} {{ '=' * 20 }} {{ 3 * 4 }} {{ [0] * 3 }}", ) == \
        f"1024 {'=' * 20} 12 [0, 0, 0]"
    assert render_template("{{ mediainfo }}", mediainfo="General") == "General"


def test_the_sandbox_still_refuses_code():
    with pytest.raises(DescriptionTemplateError):
        render_template("{{ cycler.__init__.__globals__.os }}")
