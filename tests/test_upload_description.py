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
    # I testi allargati da un metodo, un filtro o una specifica di formato.
    "{{ 'x'.ljust(5 * 10 ** 7) }}",
    "{{ 'x'.rjust(width=10 ** 8) }}",
    "{{ 'x'.zfill(10 ** 8) }}",
    "{{ 'x'|center(5 * 10 ** 7) }}",
    "{{ '%50000000s' % 'x' }}",
    "{{ '%*s' % (50000000, 'x') }}",
    "{{ '%.50000000f' % 1.0 }}",
    "{{ '%50000000s'|format('x') }}",
    "{{ '{:>50000000}'.format('x') }}",
    "{{ '{:>{w}}'.format('x', w=50000000) }}",
    "{{ ('x' * 1000).replace('x', 'y' * 10000) }}",
    "{{ ('x' * 1000)|replace('x', 'y' * 10000) }}",
    "{{ ('y' * 100000).join(range(1000)|map('string')) }}",
    "{{ range(1000)|map('string')|join('y' * 100000) }}",
    "{{ ('\t' * 1000).expandtabs(100000) }}",
    "{{ ('a\n' * 1000)|indent(100000) }}",
    "{{ ('a' * 100000)|wordwrap(1, wrapstring='y' * 1000) }}",
    "{{ [1]|batch(10 ** 9, 'x')|list }}",
    "{{ [1]|slice(10 ** 9)|list }}",
    "{{ lipsum(10 ** 7) }}",
    # Un ciclo che scrive un mega a giro: il tetto del testo scritto.
    "{% for i in range(100000) %}{{ 'x' * 999999 }}{% endfor %}",
])
def test_a_template_cannot_make_a_huge_value(source):
    """Audit 2026-10-18: la sandbox fermava il codice, non i conti. Ogni
    operazione che fa crescere un valore si controlla prima di farla; resta
    fuori quello che cresce a passi piccoli dentro un valore (vedi
    nazgarr/upload/description.py)."""
    started = time.monotonic()
    with pytest.raises(DescriptionTemplateError) as exc:
        render_template(source)
    assert exc.value.code == "upload_description_template_invalid"
    assert time.monotonic() - started < 2


def test_ordinary_arithmetic_and_repetition_still_work():
    assert render_template("{{ 2 ** 10 }} {{ '=' * 20 }} {{ 3 * 4 }} {{ [0] * 3 }}", ) == \
        f"1024 {'=' * 20} 12 [0, 0, 0]"
    assert render_template("{{ mediainfo }}", mediainfo="General") == "General"
    # Gli stessi metodi, filtri e formati, con valori normali.
    assert render_template(
        "{{ 'x'.ljust(3) }}|{{ 'ab'|center(4) }}|{{ '%3s' % 'x' }}|{{ '%s=%d'|format('a', 3) }}|"
        "{{ '{:>3}'.format('x') }}|{{ 'aXb'.replace('X', '-') }}|{{ ', '.join(['a', 'b']) }}|"
        "{{ range(3)|map('string')|join(',') }}|{{ 'a\nb'|indent(2, true) }}|{{ 'aaa bbb'|wordwrap(3) }}|"
        "{{ [1, 2, 3]|batch(2)|list }}|{{ '%(a)s' % {'a': 1} }}|{{ 100 % 7 }}|{{ lipsum(1, false, 2, 3) != '' }}"
    ) == "x  | ab |  x|a=3|  x|a-b|a, b|0,1,2|  a\n  b|aaa\nbbb|[[1, 2], [3]]|1|2|True"


def test_the_sandbox_still_refuses_code():
    with pytest.raises(DescriptionTemplateError):
        render_template("{{ cycler.__init__.__globals__.os }}")
