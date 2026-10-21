"""Pezzi del modulo Upload condivisi fra i passi del flusso v2 (docs/SPEC.md
§9): la mappa dai segnali guessit al type_id del profilo e la descrizione
dal template del tracker. L'orchestrazione dei passi vive in
nazgarr/upload/jobs.py e nazgarr/upload/worker.py. Dominio separato dal reseeding:
non tocca mai media_item/candidate/match_review/seed_job."""

import contextvars
import functools
import itertools
import logging
import re
import string
import time
import types

from jinja2 import TemplateError, nodes, pass_environment
from jinja2.compiler import CodeGenerator, Frame
from jinja2.filters import make_attrgetter
from jinja2.runtime import LoopContext, Macro
from jinja2.sandbox import ImmutableSandboxedEnvironment, SecurityError
from jinja2.utils import Namespace
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
#
# E quello che si moltiplica senza crescere (seconda revisione): [a] * 300
# dentro [b] * 300 dentro [c] * 300 è lungo 300 a ogni livello, ma il suo
# testo è 27 milioni di volte a, e str(), tojson, == o un sort lo scorrono
# tutto in una sola chiamata in C, col GIL tenuto fino alla fine: 97
# caratteri di template tenevano fermo il processo per 5 s e chiedevano un
# GB, e cambiando un numero minuti e decine di GB (OOM, e il target in
# preparing che riparte). Ogni contenitore che il template crea (un
# letterale, *, +, una chiamata, un filtro, un namespace) si misura quando
# nasce: quanto è lungo il suo testo, contando ogni riferimento ripetuto
# quante volte compare (_Budget.size). Oltre MAX_SEQUENCE è rifiutato, così
# ogni operazione su un valore del template costa al più quel tanto, e il
# tempo si controlla dopo ognuna (anche dopo un confronto e un test).
MAX_INT_BITS = 64 * 1024
MAX_SEQUENCE = 1_000_000
MAX_OUTPUT = 4 * MAX_SEQUENCE
MAX_GROWTH = 16 * MAX_SEQUENCE
MAX_TURNS = 500_000
MAX_RENDER_SECONDS = 5.0
# Una specifica di % (la chiave, la larghezza e la precisione, anche da un
# argomento con *).
_PERCENT_SPEC = re.compile(r"%(?:\(([^)]*)\))?[-#0 +]*(\*|\d+)?(?:\.(\*|\d+))?")
_TEXTS = (str, bytes)
_DICT_VIEWS = (type({}.keys()), type({}.values()), type({}.items()))
# I valori che contengono altri valori: il loro testo li scrive tutti.
_CONTAINERS = (list, tuple, dict, set, frozenset, Namespace, *_DICT_VIEWS)
# Le misure che un render ricorda, al più: oltre si ricomincia (costa solo
# rimisurare, sempre fino al tetto).
_MAX_REMEMBERED = 1 << 16
_END = object()


def _digits(number: int) -> int:
    return abs(number).bit_length() * 30103 // 100000 + 2  # le cifre, e il segno


def _leaf_size(value) -> int | None:
    """Quanto è lungo al più il testo di value da solo (str, repr o json:
    lo stesso ordine di grandezza); None per un contenitore, che si scorre."""
    if isinstance(value, str):
        return len(value) + 2  # le virgolette dentro un repr
    if isinstance(value, _CONTAINERS):
        return None
    if value is None or isinstance(value, bool):
        return 5
    if isinstance(value, int):
        return _digits(value)
    if isinstance(value, float):
        return 24
    if isinstance(value, bytes):
        return 4 * len(value) + 3  # \xNN
    if isinstance(value, range):
        return _digits(value.start) + _digits(value.stop) + _digits(value.step) + 16
    if isinstance(value, Macro):
        return len(value.name or "") + 16  # il nome della macro è nel suo repr
    return 64  # loop, cycler, Undefined, un generatore, una funzione: un repr corto


def _overhead(value) -> int:
    return 2 if isinstance(value, (list, tuple, dict)) else 16  # [], (), {}; <Namespace {}>, dict_items([])


def _attrs(namespace: Namespace) -> dict:
    return object.__getattribute__(namespace, "_Namespace__attrs")


def _children(value):
    """Quello che il testo di value scrive: gli elementi, o chiavi e valori."""
    if isinstance(value, Namespace):
        value = _attrs(value)
    if isinstance(value, dict):
        return itertools.chain.from_iterable(value.items())
    if isinstance(value, _DICT_VIEWS[2]):
        return itertools.chain.from_iterable(value)
    return iter(value)


def _count(value) -> int:
    return len(_attrs(value)) if isinstance(value, Namespace) else len(value)


def _too_big_power(left, right) -> bool:
    if isinstance(right, (int, float)) and abs(right) > 10_000:
        return True
    return isinstance(left, int) and isinstance(right, int) and right > 0 and left.bit_length() * right > MAX_INT_BITS


def _too_big_product(left, right) -> bool:
    if isinstance(left, int) and isinstance(right, int):
        return left.bit_length() + right.bit_length() > MAX_INT_BITS
    for sequence, times in ((left, right), (right, left)):
        if not isinstance(times, int):
            continue
        if isinstance(sequence, _TEXTS) and len(sequence) * times > MAX_SEQUENCE:
            return True
        # Una lista ripetuta: il suo testo (senza le parentesi) tante volte.
        if isinstance(sequence, (list, tuple)) and (_size(sequence) - 2) * times > MAX_SEQUENCE:
            return True
    return False


def _too_big_number(text: str) -> bool:
    return len(text) > len(str(MAX_SEQUENCE)) or int(text) > MAX_SEQUENCE


def _too_big_percent(fmt, args) -> bool:
    """fmt % args (operatore o filtro format): una larghezza o una
    precisione oltre il tetto, o un risultato oltre il tetto, contando il
    testo fisso, le larghezze e i valori che scrive; uno con la sua chiave
    tante volte quante la nomina ('%(x)s' * 1000 % {'x': ...})."""
    if isinstance(fmt, bytes):
        fmt = fmt.decode("latin-1")
    if not isinstance(fmt, str):
        return False
    values = args if isinstance(args, tuple) else (args,)
    numbers = [abs(v) for v in values if isinstance(v, int)]
    size, positional, starred = len(fmt), False, False
    for key, width, precision in _PERCENT_SPEC.findall(fmt):
        for number in (width, precision):
            if number == "*":
                if any(n > MAX_SEQUENCE for n in numbers):
                    return True
                starred = True
            elif number:
                if _too_big_number(number):
                    return True
                size += int(number)
        if key:
            size += _size(args.get(key) if isinstance(args, dict) else args)
        else:
            positional = True
        if size > MAX_SEQUENCE:
            return True
    if starred:
        size += sum(numbers)
    if positional:
        size += _size(args)
    return size > MAX_SEQUENCE


def _too_big_format(fmt: str, args: tuple, kwargs: dict) -> bool:
    """str.format: una larghezza o precisione oltre il tetto, o presa da un
    altro campo ('{:{w}}'), che non si può controllare prima; o un risultato
    oltre il tetto, ogni campo con il suo argomento ('{0}' * 1000 scrive
    mille volte il primo; un pezzo di un argomento, '{0[1]}', non è mai più
    lungo dell'argomento)."""
    try:
        fields = list(string.Formatter().parse(fmt))
    except ValueError:
        return False  # l'errore lo dà format stesso
    size, auto = 0, 0
    for literal, field, spec, _conversion in fields:
        size += len(literal)
        if field is None:
            continue
        if spec:
            numbers = re.findall(r"\d+", spec)
            if "{" in spec or any(_too_big_number(n) for n in numbers):
                return True
            size += sum(int(n) for n in numbers)
        head = re.match(r"[^.\[]*", field).group()
        if not head:
            value = args[auto] if auto < len(args) else None
            auto += 1
        elif head.isdigit():
            value = args[int(head)] if len(head) < 8 and int(head) < len(args) else None
        else:
            value = kwargs.get(head)
        size += _size(value)
        if size > MAX_SEQUENCE:
            return True
    return False


def _replaced_size(text, old, new, count=-1) -> int:
    kind = str if isinstance(text, str) else bytes if isinstance(text, bytes) else None
    if kind is None or not (isinstance(old, kind) and isinstance(new, kind)):
        return 0
    times = text.count(old) if old else len(text) + 1
    if isinstance(count, int) and count >= 0:
        times = min(times, count)
    return len(text) + times * (len(new) - len(old))


def _too_big_sum(left, right) -> bool:
    if isinstance(left, _TEXTS) and isinstance(right, _TEXTS):
        return len(left) + len(right) > MAX_SEQUENCE
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return _size(left) + _size(right) - 2 > MAX_SEQUENCE
    return False


def _joined_size(separator, items) -> int:
    """separator.join(items), o |join, che scrive con str() anche un
    separatore o elementi che non sono testo; un testo si unisce lettera per
    lettera, un dizionario per chiavi."""
    if isinstance(items, dict):
        items = list(items)
    if isinstance(items, _TEXTS):
        letters = len(items)
        return (len(separator) if isinstance(separator, _TEXTS) else _size(separator)) * max(letters - 1, 0) + letters
    if not isinstance(items, (list, tuple)):
        return 0
    size = (len(separator) if isinstance(separator, _TEXTS) else _size(separator)) * max(len(items) - 1, 0)
    for item in items:
        size += len(item) if isinstance(item, _TEXTS) else _size(item)
        if size > MAX_SEQUENCE:
            break
    return size


def _too_big_method(owner, name: str, args: tuple, kwargs: dict) -> bool:
    """I metodi di testi e numeri che allargano un valore: ljust(10**10),
    ('{0}' * 1000).format(...), (1).to_bytes(10**10)."""
    numbers = [v for v in (*args, *kwargs.values()) if isinstance(v, int)]
    if isinstance(owner, int):
        return name == "to_bytes" and any(n > MAX_SEQUENCE for n in numbers)
    if name in ("ljust", "rjust", "center", "zfill"):
        return any(n > MAX_SEQUENCE for n in numbers)
    if name == "expandtabs":
        tabs = owner.count("\t" if isinstance(owner, str) else b"\t")
        return len(owner) + tabs * max(numbers[0] if numbers else 8, 0) > MAX_SEQUENCE
    if name == "replace" and len(args) >= 2:
        return _replaced_size(owner, args[0], args[1], args[2] if len(args) > 2 else kwargs.get("count", -1)) \
            > MAX_SEQUENCE
    if name == "join" and args:
        return _joined_size(owner, args[0]) > MAX_SEQUENCE
    if name == "translate" and args and isinstance(args[0], dict):
        # Una tabella che sostituisce una lettera con un testo lungo.
        longest = max((len(v) for v in args[0].values() if isinstance(v, str)), default=1)
        return len(owner) * longest > MAX_SEQUENCE
    if name == "format" and isinstance(owner, str):
        return _too_big_format(owner, args, kwargs)
    if name == "format_map" and isinstance(owner, str):
        return _too_big_format(owner, (), args[0] if args and isinstance(args[0], dict) else {})
    return False


def _refuse(what: str):
    raise SecurityError(f"the result of {what} would be too large")


class _Budget:
    """Quello che un render può ancora fare (vedi MAX_GROWTH), e le misure
    dei contenitori che ha già incontrato (size)."""

    __slots__ = ("deadline", "grown", "sizes", "turns")

    def __init__(self):
        self.deadline = time.monotonic() + MAX_RENDER_SECONDS
        self.grown = 0
        self.turns = 0
        self.sizes: dict[int, tuple[object, int]] = {}

    def tick(self) -> None:
        if time.monotonic() > self.deadline:
            raise SecurityError(f"the template took more than {MAX_RENDER_SECONDS:g} seconds")

    def charge(self, amount: int) -> None:
        self.grown += amount
        if self.grown > MAX_GROWTH:
            raise SecurityError("the template builds too much text or too many items")
        self.tick()

    def grow(self, value):
        """value conta nel budget: un testo per la sua lunghezza, un
        contenitore per i suoi elementi (quello che costruirlo ha allocato:
        [b, b] non copia b), dopo averlo misurato (size): oltre
        MAX_SEQUENCE è rifiutato. Un generatore (|batch, |map...) si misura
        un elemento alla volta, quando esce."""
        if isinstance(value, _TEXTS):
            self.charge(len(value))
        elif isinstance(value, _CONTAINERS):
            if self.size(value) > MAX_SEQUENCE:
                raise SecurityError("a value the template builds would be more than a million characters as text")
            self.charge(max(_count(value), 1))
        elif isinstance(value, types.GeneratorType):
            self.tick()
            return self._checked_items(value)
        else:
            self.tick()
        return value

    def _checked_items(self, items):
        for item in items:
            if isinstance(item, _CONTAINERS):
                self.grow(item)
            yield item

    def _known(self, value) -> int | None:
        known = self.sizes.get(id(value))
        return known[1] if known is not None and known[0] is value else None

    def _remember(self, value, size: int) -> None:
        if len(self.sizes) >= _MAX_REMEMBERED:
            self.sizes.clear()
        self.sizes[id(value)] = (value, size)

    def size(self, value, indent: bool = False) -> int:
        """Quanto è lungo il testo di value (str, repr, json), contando ogni
        riferimento ripetuto quante volte compare, come lo conta str(); oltre
        MAX_SEQUENCE si ferma e dice MAX_SEQUENCE + 1. Un contenitore
        misurato resta in sizes, con il suo riferimento (così il suo id non
        si riusa): la sandbox immutabile non lo cambia più, e misurarne uno
        nuovo costa quanto i suoi elementi diretti. Un namespace invece si
        cambia ({% set ns.x = ... %}): si rimisura ogni volta, e chi lo
        contiene può averne una misura vecchia; per questo il suo testo si
        rimisura quando si scrive (_Namespace). indent: con il rientro di
        |pprint, un elemento per riga rientrato quanto è profondo (senza
        ricordare niente: le misure sono diverse)."""
        leaf = _leaf_size(value)
        if leaf is not None:
            return leaf
        known = None if indent else self._known(value)
        if known is not None:
            return known
        # In profondità senza ricorsione: per ogni contenitore aperto il suo
        # totale parziale, e running, la loro somma, che può solo crescere.
        # Il terzo elemento: quello che il contenitore aggiunge a chi lo
        # contiene (la virgola e lo spazio, il rientro), fuori dalla sua misura.
        stack = [(value, _children(value), 0)]
        totals = [_overhead(value)]
        running = totals[0]
        open_ids = {id(value)}
        namespaces: dict[int, int] = {}  # misurati in questa chiamata: intanto non cambiano
        steps = 0
        while True:
            container, children, outer = stack[-1]
            child = next(children, _END)
            if child is _END:
                stack.pop()
                total = totals.pop()
                open_ids.discard(id(container))
                if isinstance(container, Namespace):
                    namespaces[id(container)] = total
                elif not indent:
                    self._remember(container, total)
                if not stack:
                    return total
                totals[-1] += total + outer
                continue
            steps += 1
            if not steps % 4096:
                self.tick()
            weight = _leaf_size(child)
            if weight is None and not indent:
                weight = namespaces.get(id(child)) if isinstance(child, Namespace) else self._known(child)
            if weight is None and id(child) in open_ids:
                weight = 16  # dentro sé stesso, da un namespace: il repr scrive [...] o {...}
            extra = 2 + (len(stack) if indent else 0)
            if weight is None:
                stack.append((child, _children(child), extra))
                open_ids.add(id(child))
                weight = _overhead(child)
                totals.append(weight)
            else:
                totals[-1] += weight + extra
            running += weight + extra
            if running > MAX_SEQUENCE:
                return MAX_SEQUENCE + 1


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


def _size(value) -> int:
    """_Budget.size, con le misure del render in corso (o senza, fuori)."""
    return (_BUDGET.get() or _Budget()).size(value)


class _Namespace(Namespace):
    """namespace() dei template, misurato come gli altri contenitori: quando
    nasce (call) e a ogni {% set ns.x = ... %}. È l'unico valore che il
    template cambia dopo averlo creato, quindi chi lo contiene può averne
    una misura vecchia: il suo testo (repr, str) si rimisura ogni volta che
    si scrive, e conta nel budget. Le altre operazioni non lo aprono: == e
    hash sono per identità, tojson e sort lo rifiutano."""

    def __setitem__(self, name, value):
        Namespace.__setitem__(self, name, value)
        budget = _BUDGET.get()
        if budget is not None and budget.size(self) > MAX_SEQUENCE:
            _refuse("{% set %}")

    def __repr__(self):
        budget = _BUDGET.get()
        if budget is not None:
            size = budget.size(self)
            if size > MAX_SEQUENCE:
                _refuse("a namespace as text")
            budget.charge(size)
        return Namespace.__repr__(self)


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


def _ticked(function):
    """Un test ({% if x is in y %}): anche un confronto scorre i valori in C."""

    @functools.wraps(function)
    def ticked(*args, **kwargs):
        result = function(*args, **kwargs)
        _tick()
        return result

    return ticked


class _BudgetedCode(CodeGenerator):
    """Il codice dei template con '~' contato (Jinja lo compila in un join
    diretto, senza passare da call_binop), ogni lista, tupla o dizionario
    scritti nel template misurati quando nascono, e il tempo controllato
    dopo ogni confronto."""

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

    def visit_List(self, node: nodes.List, frame: Frame) -> None:
        self.write("environment.checked_container(")
        super().visit_List(node, frame)
        self.write(")")

    def visit_Tuple(self, node: nodes.Tuple, frame: Frame) -> None:
        if node.ctx != "load":  # il bersaglio di un {% for a, b in %} o di un {% set a, b = %}
            super().visit_Tuple(node, frame)
            return
        self.write("environment.checked_container(")
        super().visit_Tuple(node, frame)
        self.write(")")

    def visit_Dict(self, node: nodes.Dict, frame: Frame) -> None:
        self.write("environment.checked_container(")
        super().visit_Dict(node, frame)
        self.write(")")

    def visit_Compare(self, node: nodes.Compare, frame: Frame) -> None:
        self.write("environment.ticked(")
        super().visit_Compare(node, frame)
        self.write(")")


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


def _text(value):
    """Il testo su cui lavora un filtro che fa str() del valore (misurato:
    un contenitore lo è già quando nasce)."""
    return value if isinstance(value, _TEXTS) else str(value)


def _indented_size(value, width=4, *_args, **_kwargs) -> int:
    text = str(value)
    step = width if isinstance(width, int) else len(str(width))
    return len(text) + (text.count("\n") + 1) * max(step, 0)


def _wrapped_size(value, width=79, break_long_words=True, wrapstring=None, *_args, **_kwargs) -> int:
    text = str(value)
    breaks = len(text) // max(width, 1) + text.count("\n") + 1 if isinstance(width, int) else 0
    return len(text) + breaks * len(wrapstring if isinstance(wrapstring, str) else "\n")


def _urlized_size(value, trim_url_limit=None, nofollow=False, target=None, rel=None, *_args, **_kwargs) -> int:
    """|urlize: ogni indirizzo (almeno cinque caratteri l'uno) scritto due
    volte, con il suo tag e target e rel ripetuti."""
    text = str(value)
    each = len(str(target or "")) + len(str(rel or "")) + 64
    return 3 * len(text) + (len(text) // 5 + 1) * each


def _int_over(*args, **kwargs) -> bool:
    return any(isinstance(v, int) and v > MAX_SEQUENCE for v in (*args[1:], *kwargs.values()))


@pass_environment
def _checked_sum(environment, iterable, attribute=None, start=0):
    """|sum: su liste o tuple Python copia la somma a ogni passo, in C: n
    passi per la lunghezza finale ([[1]] * 100000 |sum(start=[]) teneva il
    GIL per secondi)."""
    if attribute is not None:
        iterable = map(make_attrgetter(environment, attribute), iterable)
    items = list(iterable)
    if isinstance(start, (list, tuple)) or any(isinstance(item, (list, tuple)) for item in items):
        length = sum(len(v) for v in (start, *items) if isinstance(v, (list, tuple)))
        if len(items) * length > MAX_GROWTH:
            _refuse("|sum")
    return sum(items, start)


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
        self.filters["sum"] = _checked_sum
        self.globals["namespace"] = _Namespace
        _guard_filter(self.filters, "center", _int_over)
        _guard_filter(self.filters, "batch", _int_over)
        _guard_filter(self.filters, "slice", _int_over)
        _guard_filter(self.filters, "format", lambda value, *args, **kwargs: _too_big_percent(
            _text(value), kwargs or args))
        _guard_filter(self.filters, "indent", lambda *args, **kwargs: _indented_size(*args, **kwargs) > MAX_SEQUENCE)
        _guard_filter(self.filters, "wordwrap", lambda *args, **kwargs: _wrapped_size(*args, **kwargs) > MAX_SEQUENCE)
        _guard_filter(self.filters, "urlize", lambda *args, **kwargs: _urlized_size(*args, **kwargs) > MAX_SEQUENCE)
        # |replace fa str() anche del vecchio e del nuovo.
        _guard_filter(self.filters, "replace", lambda value, old="", new="", count=None: _replaced_size(
            str(value), str(old), str(new), -1 if count is None else count) > MAX_SEQUENCE)
        _guard_filter(self.filters, "join", lambda value, d="", attribute=None: _joined_size(d, value) > MAX_SEQUENCE,
                      listed=True)
        _guard_filter(self.filters, "pprint", lambda value: (_BUDGET.get() or _Budget()).size(value, indent=True)
                      > MAX_SEQUENCE)
        lipsum = self.globals["lipsum"]

        def capped_lipsum(n=5, html=True, min=20, max=100):
            if not all(isinstance(v, int) for v in (n, min, max)) or n > 100 or max > 1000:
                _refuse("lipsum")
            return lipsum(n, html, min, max)

        self.globals["lipsum"] = capped_lipsum
        for name, function in list(self.filters.items()):
            self.filters[name] = _charged(function)
        for name, function in list(self.tests.items()):
            self.tests[name] = _ticked(function)

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
    def checked_container(value):
        return _grown(value)

    @staticmethod
    def ticked(value):
        _tick()
        return value

    @staticmethod
    def checked_concat(parts: tuple) -> tuple:
        # Misurati prima di scriverli: lo str() di un contenitore enorme era
        # già il conto da evitare.
        budget = _BUDGET.get() or _Budget()
        size = 0
        for part in parts:
            size += len(part) if isinstance(part, str) else budget.size(part)
            if size > MAX_SEQUENCE:
                _refuse("~")
        budget.charge(size)
        return parts

    def call_binop(self, context, operator, left, right):
        if ((operator == "**" and _too_big_power(left, right)) or (operator == "*" and _too_big_product(left, right))
                or (operator == "%" and _too_big_percent(left, right))
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
        owner = getattr(method, "__self__", None)
        if isinstance(owner, (*_TEXTS, int)):
            name = getattr(method, "__name__", "")
            if name == "join" and args and not isinstance(args[0], (str, list, tuple, dict)):
                args = (list(args[0]), *args[1:])  # per contarlo prima; finito, come range
            if _too_big_method(owner, name, args, kwargs):
                _refuse(f".{name}()")
        budget = _BUDGET.get()
        if budget is not None:
            # Gli argomenti insieme: una macro li ritrova in varargs e kwargs,
            # cycler() in .items, dict() nel suo risultato.
            total = 0
            for value in (*args, *kwargs.values()):
                total += budget.size(value)
                if total > MAX_SEQUENCE:
                    _refuse("a call's arguments")
        if isinstance(__obj, LoopContext) and args:
            # loop(...) di un ciclo ricorsivo: i suoi giri contano come gli altri.
            args = (_Turns(args[0]), *args[1:])
        # Anche quello che una chiamata restituisce (un metodo dei testi, una
        # macro, caller(), dict(), namespace()) conta nel budget, misurato.
        return _grown(super().call(__context, __obj, *args, **kwargs))


# Il template lo scrive l'utente (profilo di upload del tracker): sempre in
# una sandbox, mai jinja2.Template, che permetterebbe di eseguire codice sul
# server con {{ cycler.__init__.__globals__.os... }}. Nessun escaping HTML: è
# BBCode, non una pagina.
_TEMPLATES = _DescriptionTemplates(autoescape=False)


class DescriptionTemplateError(CodedError):
    """Il template della descrizione non si può usare (sintassi, o qualcosa
    che la sandbox non permette)."""


# Quello che un template inutilizzabile solleva, compilandolo o scrivendolo:
# la sintassi e la sandbox (TemplateError, SecurityError compresa), un conto
# che non si può fare ({{ 1/0 }}, un numero da più di 4300 cifre da
# scrivere), e un'annidatura troppo profonda per il parser di Jinja
# (RecursionError) o per il compilatore di Python (SyntaxError).
_TEMPLATE_ERRORS = (TemplateError, ArithmeticError, TypeError, ValueError, MemoryError, RecursionError, SyntaxError)


def _invalid(exc: BaseException) -> DescriptionTemplateError:
    return DescriptionTemplateError("upload_description_template_invalid", error=str(exc) or type(exc).__name__)


def _render(source: str, values: dict) -> str:
    """Il render a pezzi, come escono: un ciclo che scrive un mega a giro si
    ferma al tetto, invece di accumulare tutto prima di unirlo. Con il suo
    budget (_Budget), dalla compilazione all'ultimo pezzo."""
    budget = _Budget()
    token = _BUDGET.set(budget)
    try:
        parts, size = [], 0
        for part in _TEMPLATES.from_string(source).generate(**values):
            size += len(part)
            if size > MAX_OUTPUT:
                _refuse("the template")
            budget.tick()
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
    except _TEMPLATE_ERRORS as exc:
        raise _invalid(exc) from exc
    finally:
        _BUDGET.reset(token)


def render_template(source: str, **values) -> str:
    try:
        return _render(source, values)
    except _TEMPLATE_ERRORS as exc:
        raise _invalid(exc) from exc


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
