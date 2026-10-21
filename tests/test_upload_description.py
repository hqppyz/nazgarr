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
    operazione che fa crescere un valore si controlla prima di farla (e
    quello che cresce a passi piccoli, sotto, ha il budget del render)."""
    started = time.monotonic()
    with pytest.raises(DescriptionTemplateError) as exc:
        render_template(source)
    assert exc.value.code == "upload_description_template_invalid"
    assert time.monotonic() - started < 2


@pytest.mark.parametrize("source", [
    # '~' e '+' raddoppiati in un ciclo: 128 MB in 0,05 s.
    "{% set ns = namespace(s='x' * 1000000) %}{% for i in range(7) %}{% set ns.s = ns.s ~ ns.s %}{% endfor %}",
    "{% set ns = namespace(s='x') %}{% for i in range(40) %}{% set ns.s = ns.s ~ ns.s %}{% endfor %}",
    "{% set ns = namespace(l=[0] * 500000) %}{% for i in range(10) %}{% set ns.l = ns.l + ns.l %}{% endfor %}",
    "{% set ns = namespace(s='x' * 500000) %}{% for i in range(20) %}{% set ns.s = ns.s + ns.s %}{% endfor %}",
    # Testi diversi da un mega, uno a giro: nessuno troppo grande, tutti insieme sì.
    "{% set ns = namespace(l=[]) %}{% for i in range(100000) %}{% set ns.l = ns.l + [('x' * 999999) ~ i] %}"
    "{% endfor %}",
    "{% set ns = namespace(l=[]) %}{% for i in range(100000) %}{% set ns.l = ns.l + [range(100000)|join(',')] %}"
    "{% endfor %}",
    # Lo stesso da un {% set %} a blocco e da una macro.
    "{% set ns = namespace(s='x' * 500000) %}{% for i in range(20) %}{% set ns.s %}{{ ns.s }}{{ ns.s }}"
    "{% endset %}{% endfor %}",
    "{% macro d(s) %}{{ s }}{{ s }}{% endmacro %}{% set ns = namespace(s='x' * 500000) %}"
    "{% for i in range(20) %}{% set ns.s = d(ns.s) %}{% endfor %}",
    # CPU senza fine: cicli uno dentro l'altro, anche ricorsivi o su un testo.
    "{% for i in range(100000) %}{% for j in range(100000) %}{% endfor %}{% endfor %}",
    "{% for x in range(1000) recursive %}{% if loop.depth < 4 %}{{ loop(range(1000)) }}{% endif %}{% endfor %}",
    "{% set s = 'x' * 1000000 %}{% for a in s %}{% for b in s %}{% endfor %}{% endfor %}",
])
def test_a_template_cannot_grow_a_value_or_loop_without_end(source):
    """Revisione dell'audit 2026-10-18: ogni render ha un budget di quanto
    costruisce, di quanti giri fanno i suoi cicli e di tempo."""
    started = time.monotonic()
    with pytest.raises(DescriptionTemplateError) as exc:
        render_template(source)
    assert exc.value.code == "upload_description_template_invalid"
    assert time.monotonic() - started < 2


def test_a_render_has_a_time_budget(monkeypatch):
    # Pochi giri, ognuno lento: né il testo né i giri bastano a fermarlo.
    from nazgarr.upload import description

    monkeypatch.setattr(description, "MAX_RENDER_SECONDS", 0.2)
    started = time.monotonic()
    with pytest.raises(DescriptionTemplateError) as exc:
        render_template("{% for i in range(100000) %}{% for j in range(3) %}{% set x = range(100000)|sum %}"
                        "{% endfor %}{% endfor %}")
    assert "seconds" in exc.value.params["error"]
    assert time.monotonic() - started < 2


def test_loops_concatenations_and_blocks_of_a_real_description_still_work():
    assert render_template(
        "{% for u in screenshot_urls %}[img]{{ u }}[/img]{% if not loop.last %} {% endif %}{% endfor %}|"
        "{{ mediainfo ~ '!' }}|{% set x %}a{{ 1 }}{% endset %}{{ x }}|{{ [1] + [2] }}|{{ 'a' + 'b' }}|"
        "{{ screenshot_urls|length }}{% for u in screenshot_urls %}{{ loop.length }}{% endfor %}|"
        "{% for x in tree recursive %}{{ x.n }}{% if x.c %}({{ loop(x.c) }}){% endif %}{% endfor %}",
        screenshot_urls=["a", "b"], mediainfo="MI", tree=[{"n": 1, "c": [{"n": 2, "c": []}]}],
    ) == "[img]a[/img] [img]b[/img]|MI!|a1|[1, 2]|ab|222|1(2)"


def test_check_template_compiles_without_rendering():
    from nazgarr.upload.description import MAX_TEMPLATE_LENGTH, check_template

    check_template("{% for i in range(100000) %}{% for j in range(100000) %}{% endfor %}{% endfor %}")  # non gira
    for source in ("{% if %}", "{{ x|no_such_filter }}", "x" * (MAX_TEMPLATE_LENGTH + 1)):
        with pytest.raises(DescriptionTemplateError):
            check_template(source)


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
