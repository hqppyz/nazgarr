"""Pezzi del modulo Upload condivisi fra i passi del flusso v2 (docs/SPEC.md
§9): la mappa dai segnali guessit al type_id del profilo e la descrizione
dal template del tracker. L'orchestrazione dei passi vive in
nazgarr/upload/jobs.py e nazgarr/upload/worker.py. Dominio separato dal reseeding:
non tocca mai media_item/candidate/match_review/seed_job."""

import contextvars
import functools
import logging
import re
import string
import time

from jinja2 import TemplateError, nodes
from jinja2.compiler import CodeGenerator, Frame
from jinja2.runtime import LoopContext
from jinja2.sandbox import ImmutableSandboxedEnvironment, SecurityError
from sqlalchemy.orm import Session

from nazgarr.core import settings_repo
from nazgarr.core.errors import CodedError
from nazgarr.core.models import TrackerUploadProfile
from nazgarr.core.version import __version__

logger = logging.getLogger(__name__)

# Mapping da segnali guessit a chiavi type_id — euristica best-effort,
# MAI la fonte di verità: category_id/resolution_id si ricavano in modo
# affidabile (content_type risolto, screen_size di guessit combacia quasi
# sempre con le chiavi resolution_id_map), ma la distinzione
PROJECT_URL = "https://github.com/lktorrentz/nazgarr"
# Servito da GitHub (repo pubblico): il tracker non vede mai l'istanza.
CREDIT_LOGO_URL = "https://raw.githubusercontent.com/lktorrentz/nazgarr/main/docs/assets/nazgarr-credit.png"


def credit_line() -> str:
    """La riga sempre in fondo a ogni descrizione, dopo la firma dell'utente:
    centrata, staccata da quello che c'è sopra (render_description)."""
    return (
        f"[center][url={PROJECT_URL}][img=16]{CREDIT_LOGO_URL}[/img][/url] "
        f"[size=14]Uploaded with [url={PROJECT_URL}]Nazgarr[/url] v{__version__}[/size][/center]"
    )


# Quanto può crescere un numero o un testo dentro un template (audit
# 2026-10-18): la sandbox ferma il codice, non i conti. 9**(9**8) teneva il
# GIL per ore (tutto il processo fermo, API e scheduler compresi), e
# 'x' * 10**10, 'x'.ljust(10**10) o '%10000000000s' % 'x' chiedevano 10 GB
# in un colpo. Ogni operazione che fa crescere un valore si controlla prima.
# E il testo del render ha un tetto mentre si scrive.
#
# Poi quello che cresce a passi piccoli, un giro alla volta (revisione
# dell'audit): '~' o '+' raddoppiati in un ciclo arrivavano a 128 MB in
# 0,05 s, e due range(100000) uno dentro l'altro erano CPU senza fine. Ogni
# render ha un budget (_Budget): quanto testo e quanti elementi le sue
# operazioni costruiscono in tutto (MAX_GROWTH, sommando ogni risultato: un
# valore che poi si butta conta lo stesso), quanti giri fanno i suoi cicli
# (MAX_TURNS) e quanto tempo ha (MAX_RENDER_SECONDS). Una descrizione vera
# ne usa una frazione piccola: un mediainfo, qualche screenshot.
MAX_INT_BITS = 64 * 1024
MAX_SEQUENCE = 1_000_000
MAX_OUTPUT = 4 * MAX_SEQUENCE
MAX_GROWTH = 16 * MAX_SEQUENCE
MAX_TURNS = 500_000
MAX_RENDER_SECONDS = 5.0
# Una specifica di % (larghezza e precisione, anche da un argomento con *).
_PERCENT_SPEC = re.compile(r"%(?:\([^)]*\))?[-#0 +]*(\*|\d+)?(?:\.(\*|\d+))?")


def _too_big_power(left, right) -> bool:
    if isinstance(right, (int, float)) and abs(right) > 10_000:
        return True
    return isinstance(left, int) and isinstance(right, int) and right > 0 and left.bit_length() * right > MAX_INT_BITS


def _too_big_product(left, right) -> bool:
    if isinstance(left, int) and isinstance(right, int):
        return left.bit_length() + right.bit_length() > MAX_INT_BITS
    for sequence, times in ((left, right), (right, left)):
        if isinstance(sequence, (str, list, tuple)) and isinstance(times, int) and len(sequence) * times > MAX_SEQUENCE:
            return True
    return False


def _too_big_number(text: str) -> bool:
    return len(text) > len(str(MAX_SEQUENCE)) or int(text) > MAX_SEQUENCE


def _too_wide_percent(fmt, args) -> bool:
    """fmt % args (operatore o filtro format) con una larghezza o una
    precisione oltre il tetto."""
    if not isinstance(fmt, str):
        return False
    values = args if isinstance(args, tuple) else (args,)
    for spec in _PERCENT_SPEC.findall(fmt):
        for number in spec:
            if number == "*" and any(isinstance(v, int) and abs(v) > MAX_SEQUENCE for v in values):
                return True
            if number.isdigit() and _too_big_number(number):
                return True
    return False


def _too_wide_format(fmt: str) -> bool:
    """str.format: una larghezza o precisione oltre il tetto, o presa da un
    altro campo ('{:{w}}'), che non si può controllare prima."""
    try:
        fields = list(string.Formatter().parse(fmt))
    except ValueError:
        return False  # l'errore lo dà format stesso
    for _literal, field, spec, _conversion in fields:
        if field is None or not spec:
            continue
        if "{" in spec or any(_too_big_number(n) for n in re.findall(r"\d+", spec)):
            return True
    return False


def _replaced_size(text, old, new, count=-1) -> int:
    if not (isinstance(text, str) and isinstance(old, str) and isinstance(new, str)):
        return 0
    times = text.count(old) if old else len(text) + 1
    if isinstance(count, int) and count >= 0:
        times = min(times, count)
    return len(text) + times * (len(new) - len(old))


def _too_big_sum(left, right) -> bool:
    return (isinstance(left, (str, list, tuple)) and isinstance(right, (str, list, tuple))
            and len(left) + len(right) > MAX_SEQUENCE)


def _joined_size(separator, items) -> int:
    if not isinstance(separator, str):
        return 0
    return len(separator) * max(len(items) - 1, 0) + sum(len(item) for item in items if isinstance(item, str))


def _too_big_str_call(text: str, name: str, args: tuple, kwargs: dict) -> bool:
    """I metodi dei testi che allargano un valore: ljust(10**10)."""
    numbers = [v for v in (*args, *kwargs.values()) if isinstance(v, int)]
    if name in ("ljust", "rjust", "center", "zfill"):
        return any(n > MAX_SEQUENCE for n in numbers)
    if name == "expandtabs":
        return len(text) + text.count("\t") * max(numbers[0] if numbers else 8, 0) > MAX_SEQUENCE
    if name == "replace" and len(args) >= 2:
        return _replaced_size(text, args[0], args[1], args[2] if len(args) > 2 else kwargs.get("count", -1)) \
            > MAX_SEQUENCE
    if name == "join" and args:
        return _joined_size(text, args[0]) > MAX_SEQUENCE
    if name in ("format", "format_map"):
        return _too_wide_format(text)
    return False


def _refuse(what: str):
    raise SecurityError(f"the result of {what} would be too large")


class _Budget:
    """Quello che un render può ancora fare (vedi MAX_GROWTH)."""

    __slots__ = ("deadline", "grown", "turns")

    def __init__(self):
        self.deadline = time.monotonic() + MAX_RENDER_SECONDS
        self.grown = 0
        self.turns = 0

    def tick(self) -> None:
        if time.monotonic() > self.deadline:
            raise SecurityError(f"the template took more than {MAX_RENDER_SECONDS:g} seconds")

    def grow(self, value):
        if isinstance(value, (str, list, tuple)):
            self.grown += len(value)
            if self.grown > MAX_GROWTH:
                raise SecurityError("the template builds too much text or too many items")
        self.tick()
        return value


# Il budget del render in corso, nel thread che lo fa (il worker, o una
# richiesta). Fuori da un render (Jinja che piega le costanti mentre
# compila) non c'è: niente da contare.
_BUDGET: contextvars.ContextVar[_Budget | None] = contextvars.ContextVar("description_budget", default=None)


def _tick() -> None:
    budget = _BUDGET.get()
    if budget is not None:
        budget.tick()


def _grown(value):
    budget = _BUDGET.get()
    return value if budget is None else budget.grow(value)


class _Turns:
    """L'iterabile di un {% for %} (o di un loop(...) ricorsivo), contato a
    ogni giro. La lunghezza resta quella di prima: loop.length non la
    ricalcola scorrendolo."""

    __slots__ = ("_items",)

    def __init__(self, items):
        self._items = items

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        budget = _BUDGET.get()
        for item in self._items:
            if budget is not None:
                budget.turns += 1
                if budget.turns > MAX_TURNS:
                    raise SecurityError(f"the template's loops ran more than {MAX_TURNS} times")
                if budget.turns % 256 == 0:
                    budget.tick()
            yield item


def _charged(function):
    """Un filtro il cui risultato conta nel budget (|list, |join, |string...)."""

    @functools.wraps(function)  # anche jinja_pass_arg: Jinja passa lo stesso contesto
    def charged(*args, **kwargs):
        return _grown(function(*args, **kwargs))

    return charged


class _BudgetedCode(CodeGenerator):
    """Il codice dei template con '~' contato: Jinja lo compila in un join
    diretto, senza passare da call_binop."""

    def visit_Concat(self, node: nodes.Concat, frame: Frame) -> None:
        # Come CodeGenerator.visit_Concat, con i pezzi contati prima del join.
        if frame.eval_ctx.volatile:
            func_name = "(markup_join if context.eval_ctx.volatile else str_join)"
        elif frame.eval_ctx.autoescape:
            func_name = "markup_join"
        else:
            func_name = "str_join"
        self.write(f"{func_name}(environment.checked_concat((")
        for arg in node.nodes:
            self.visit(arg, frame)
            self.write(", ")
        self.write(")))")


def _guard_filter(filters: dict, name: str, too_big, listed: bool = False) -> None:
    """Un filtro di Jinja che allarga un valore, con il suo controllo prima
    (too_big riceve gli stessi argomenti, senza il contesto che alcuni
    filtri vogliono per primo). listed: il valore, se arriva da un
    generatore (|map), diventa una lista per contarlo; finito, come range."""
    original = filters[name]
    skip = 1 if getattr(original, "jinja_pass_arg", None) is not None else 0

    @functools.wraps(original)
    def guarded(*args, **kwargs):
        if listed and len(args) > skip and not isinstance(args[skip], (str, list, tuple, dict)):
            args = (*args[:skip], list(args[skip]), *args[skip + 1:])
        if too_big(*args[skip:], **kwargs):
            _refuse(f"|{name}")
        return original(*args, **kwargs)

    filters[name] = guarded


def _indented_size(value, width=4, *_args, **_kwargs) -> int:
    text = str(value)
    step = width if isinstance(width, int) else len(str(width))
    return len(text) + (text.count("\n") + 1) * max(step, 0)


def _wrapped_size(value, width=79, break_long_words=True, wrapstring=None, *_args, **_kwargs) -> int:
    text = str(value)
    breaks = len(text) // max(width, 1) + text.count("\n") + 1 if isinstance(width, int) else 0
    return len(text) + breaks * len(wrapstring if isinstance(wrapstring, str) else "\n")


def _int_over(*args, **kwargs) -> bool:
    return any(isinstance(v, int) and v > MAX_SEQUENCE for v in (*args[1:], *kwargs.values()))


class _DescriptionTemplates(ImmutableSandboxedEnvironment):
    """La sandbox, con ogni operazione che fa crescere un valore controllata
    prima di farla (come suggerisce la documentazione di Jinja): **, * e %,
    i metodi dei testi (call) e i filtri che allargano. Intercettare gli
    operatori spegne anche il calcolo dei valori costanti quando il
    template si compila, che avveniva prima di qualsiasi controllo."""

    intercepted_binops = frozenset({"**", "*", "%", "+"})
    code_generator_class = _BudgetedCode

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Un {% set x %}...{% endset %} senza filtro ne riceve uno che non fa
        # niente, così il testo che raccoglie conta come quello di un filtro.
        self.filters["_charged"] = lambda value: value
        _guard_filter(self.filters, "center", _int_over)
        _guard_filter(self.filters, "batch", _int_over)
        _guard_filter(self.filters, "slice", _int_over)
        _guard_filter(self.filters, "format", lambda value, *args, **kwargs: _too_wide_percent(
            value, kwargs or args))
        _guard_filter(self.filters, "indent", lambda *args, **kwargs: _indented_size(*args, **kwargs) > MAX_SEQUENCE)
        _guard_filter(self.filters, "wordwrap", lambda *args, **kwargs: _wrapped_size(*args, **kwargs) > MAX_SEQUENCE)
        _guard_filter(self.filters, "replace", lambda value, old="", new="", count=None: _replaced_size(
            str(value), old, new, -1 if count is None else count) > MAX_SEQUENCE)
        _guard_filter(self.filters, "join", lambda value, d="", attribute=None: isinstance(value, (list, tuple))
                      and _joined_size(d, value) > MAX_SEQUENCE, listed=True)
        lipsum = self.globals["lipsum"]

        def capped_lipsum(n=5, html=True, min=20, max=100):
            if not all(isinstance(v, int) for v in (n, min, max)) or n > 100 or max > 1000:
                _refuse("lipsum")
            return lipsum(n, html, min, max)

        self.globals["lipsum"] = capped_lipsum
        for name, function in list(self.filters.items()):
            self.filters[name] = _charged(function)

    def _parse(self, source, name, filename):
        template = super()._parse(source, name, filename)
        # Ogni {% for %} scorre il suo iterabile attraverso _Turns: i giri dei
        # cicli non passano da nessun'altra operazione che la sandbox veda.
        for loop in list(template.find_all(nodes.For)):
            loop.iter = nodes.Call(nodes.EnvironmentAttribute("budgeted_turns"), [loop.iter], [], None, None,
                                   lineno=loop.iter.lineno)
        for block in list(template.find_all(nodes.AssignBlock)):
            if block.filter is None:
                block.filter = nodes.Filter(None, "_charged", [], [], None, None, lineno=block.lineno)
        template.set_environment(self)
        return template

    @staticmethod
    def budgeted_turns(items):
        return _Turns(items)

    @staticmethod
    def checked_concat(parts: tuple) -> tuple:
        size = sum(len(part) if isinstance(part, str) else len(str(part)) for part in parts)
        if size > MAX_SEQUENCE:
            _refuse("~")
        budget = _BUDGET.get()
        if budget is not None:
            budget.grown += size
            budget.grow(None)  # il controllo del totale e del tempo
            if budget.grown > MAX_GROWTH:
                raise SecurityError("the template builds too much text or too many items")
        return parts

    def call_binop(self, context, operator, left, right):
        if ((operator == "**" and _too_big_power(left, right)) or (operator == "*" and _too_big_product(left, right))
                or (operator == "%" and _too_wide_percent(left, right))
                or (operator == "+" and _too_big_sum(left, right))):
            _refuse(operator)
        return _grown(super().call_binop(context, operator, left, right))

    def getattr(self, obj, attribute):
        _tick()
        return super().getattr(obj, attribute)

    def getitem(self, obj, argument):
        _tick()
        return super().getitem(obj, argument)

    def call(__self, __context, __obj, *args, **kwargs):  # i nomi di Jinja: mai in conflitto con i kwargs
        # str.format passa da un involucro della sandbox (wrap_str_format):
        # il metodo vero, con il suo testo, è in __wrapped__.
        method = getattr(__obj, "__wrapped__", __obj)
        text = getattr(method, "__self__", None)
        if isinstance(text, str):
            name = getattr(method, "__name__", "")
            if name == "join" and args and not isinstance(args[0], (str, list, tuple)):
                args = (list(args[0]), *args[1:])  # per contarlo prima; finito, come range
            if _too_big_str_call(text, name, args, kwargs):
                _refuse(f".{name}()")
        if isinstance(__obj, LoopContext) and args:
            # loop(...) di un ciclo ricorsivo: i suoi giri contano come gli altri.
            args = (_Turns(args[0]), *args[1:])
        # Anche quello che una chiamata restituisce (un metodo dei testi, una
        # macro, caller()) conta nel budget.
        return _grown(super().call(__context, __obj, *args, **kwargs))


# Il template lo scrive l'utente (profilo di upload del tracker): sempre in
# una sandbox, mai jinja2.Template, che permetterebbe di eseguire codice sul
# server con {{ cycler.__init__.__globals__.os... }}. Nessun escaping HTML: è
# BBCode, non una pagina.
_TEMPLATES = _DescriptionTemplates(autoescape=False)


class DescriptionTemplateError(CodedError):
    """Il template della descrizione non si può usare (sintassi, o qualcosa
    che la sandbox non permette)."""


def _render(source: str, values: dict) -> str:
    """Il render a pezzi, come escono: un ciclo che scrive un mega a giro si
    ferma al tetto, invece di accumulare tutto prima di unirlo. Con il suo
    budget (_Budget), dalla compilazione all'ultimo pezzo."""
    token = _BUDGET.set(_Budget())
    try:
        parts, size = [], 0
        for part in _TEMPLATES.from_string(source).generate(**values):
            size += len(part)
            if size > MAX_OUTPUT:
                _refuse("the template")
            parts.append(part)
        return "".join(parts)
    finally:
        _BUDGET.reset(token)


# Un template più lungo non serve a una descrizione (quelli inclusi sono di
# qualche KB), e la sua compilazione è il lavoro che si fa prima del budget.
MAX_TEMPLATE_LENGTH = 100_000


def check_template(source: str) -> None:
    """Il template si compila (sintassi, filtri che esistono) e non è troppo
    lungo: DescriptionTemplateError se no. Al salvataggio del profilo:
    prima si salvava qualunque testo, e l'errore usciva solo al primo upload
    verso quel tracker. Compilare è sicuro: Jinja non piega più le
    operazioni che crescono (intercepted_binops), e gli altri valori costanti
    sono grandi al più quanto il testo."""
    if len(source) > MAX_TEMPLATE_LENGTH:
        raise DescriptionTemplateError("upload_description_template_invalid",
                                       error=f"longer than {MAX_TEMPLATE_LENGTH} characters")
    token = _BUDGET.set(_Budget())
    try:
        _TEMPLATES.from_string(source)
    except TemplateError as exc:
        raise DescriptionTemplateError("upload_description_template_invalid", error=str(exc)) from exc
    finally:
        _BUDGET.reset(token)


def render_template(source: str, **values) -> str:
    try:
        return _render(source, values)
    except TemplateError as exc:  # SecurityError compresa
        raise DescriptionTemplateError("upload_description_template_invalid", error=str(exc)) from exc
    except (ArithmeticError, TypeError, ValueError, MemoryError, RecursionError) as exc:
        # Un conto del template che non si può fare ({{ 1/0 }}, un numero da
        # più di 4300 cifre da scrivere): lo stesso errore, con il suo codice.
        raise DescriptionTemplateError("upload_description_template_invalid", error=str(exc)) from exc


def render_description(
    session: Session, profile: TrackerUploadProfile, mediainfo: str, screenshot_urls: list[str], notes: str = ""
) -> str:
    """Il template Jinja2 del profilo, con l'intestazione in cima e la firma
    in fondo, entrambe facoltative (Configuration > Upload), e per ultima la
    riga di Nazgarr (credit_line), sempre."""
    rendered = render_template(
        profile.description_template or "{{ mediainfo }}",
        mediainfo=mediainfo or "", screenshot_urls=screenshot_urls, notes=notes,
    )
    header = settings_repo.get_setting(session, "upload_description_header")
    signature = settings_repo.get_setting(session, "upload_description_signature")
    body = "\n\n".join(part for part in (header, rendered, signature) if part)
    # Una riga vuota in più prima dei crediti: staccati dal resto.
    return f"{body}\n\n\n{credit_line()}"
