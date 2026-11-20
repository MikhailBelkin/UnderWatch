"""The one list of everything the body can do: each action and each lasting activity is a single entry here.

An action entry (ACTIONS) says:
  feed     — words for the life feed («варит и пьёт кофе»);
  at       — the place it walks to by itself (None — does it where it stands);
  loop     — the lasting activity it leaves the body in (see LOOPS); "" — keeps the current one, as a gesture does; None — ends up standing;
  doc      — what the model is told it does; no doc — the model can't choose it (it comes from gifts or time together);
  args     — how the model writes the parameters in the doc, e.g. "{place}";
  page     — the page's words, if they differ from the feed's (the page speaks to the guest: «с вами»);
  needs    — what it does to the needs at once: {"energy": 4};
  secs     — how long the body is busy with it mid-chain, when it's a long animation (cooking, the shower);
  lasts    — a lasting activity the model gives minutes to;
  natural  — a place where just walking up means doing this («went to the TV» — watches TV);
  gift     — can be done with a gifted thing;
  gesture  — the page's animation for a plain gesture;
  prop     — what the page puts in her hand for an action with no animation of its own;
  when     — a check done before she does it: a function of the action that returns None if fine,
             or the line for the feed explaining why not (then the action is dropped, or replaced by `instead`);
  instead  — what she does instead when `when` says no: a function of the action, returning another action;
  asked    — only when the guest asks for it in the chat.

The action's own effect on the world, if it has one, is a function in life/body/<theme>.py (its EFFECTS);
an action the page has no special animation for is played from this entry: walk to `at`, the `gesture`, then the `loop`.

A loop entry (LOOPS) says: label — words for what she is doing; page — the page's words; needs — change per minute;
pose — an existing loop whose pose the page borrows for a new one; prop — what she holds meanwhile."""
from types import SimpleNamespace

from .context import S, g
from .clock import is_awake_time, now, today_sleep
from .world import OUTFIT_TYPES

FIELDS = {"feed": "", "at": None, "loop": None, "doc": None, "args": "", "page": None, "needs": {}, "secs": 0, "lasts": False,
          "natural": None, "gift": False, "gesture": None, "prop": None, "when": None, "instead": None, "asked": False}
LOOP_FIELDS = {"label": "", "page": None, "needs": {}, "pose": None, "prop": None}


def A(feed, **kw):
    bad = set(kw) - set(FIELDS)
    assert not bad, f"unknown action fields: {bad}"
    return SimpleNamespace(**{**FIELDS, "feed": feed, **kw})


def L(label, **kw):
    bad = set(kw) - set(LOOP_FIELDS)
    assert not bad, f"unknown loop fields: {bad}"
    return SimpleNamespace(**{**LOOP_FIELDS, "label": label, **kw})


def _route():
    from .life import route  # the route knows whether it's safe outside; imported late, it needs the catalogue itself
    return route


def not_sleepy(a):
    """In the daytime she can only fall asleep when she's worn out or bedtime is close."""
    t = now()
    left = (today_sleep(t) - t).total_seconds() / 60
    if is_awake_time(t) and S["needs"]["energy"] >= 30 and left > 15:
        return f"Хотел{g('', 'а')} лечь спать, но сна ни в одном глазу (бодрость {int(S['needs']['energy'])}) — вместо этого просто прилег{g('', 'ла')}."


OUTFITS_DOC = ", ".join(f"{k} — {v}" for k, v in OUTFIT_TYPES.items())

ACTIONS = {
    # walking and gestures
    "walk_to": A("идёт", args="{place}", doc="пойти к месту"),
    "wave": A("машет", loop="", gesture="wave"),
    "nod": A("кивает", loop="", gesture="nod"),
    "shake_head": A("мотает головой", loop="", gesture="shake"),
    "shrug": A("пожимает плечами", loop="", gesture="shrug"),
    "jump": A("прыгает", gesture="jump"),
    "dance": A("танцует", gesture="dance", needs={"fun": 10, "energy": -1.5, "hygiene": -5}),
    "think": A("думает", loop="", gesture="think"),
    "laugh": A("смеётся", loop="", gesture="laugh", needs={"fun": 3}),
    "bow": A("кланяется", loop="", gesture="bow"),
    "stretch": A("потягивается", gesture="stretch"),
    # sitting, the TV, the console, music
    "sit": A("сидит на диване", at="sofa", loop="sit", page="садится", lasts=True, natural="sofa",
             doc="сесть на диван в кают-компании (сесть на что-то другое — rest{on, sit}, например rest{stool, sit} — на барный стул)"),
    "stand": A("встаёт", doc="встать"),
    "watch_tv": A("смотрит кино", at="sofa", loop="watch", page="смотрит кино", lasts=True, natural="tv",
                  doc="сесть на диван и смотреть кино или сериал из бортовой фильмотеки на экране кают-компании"),
    "tv_off": A("выключает экран", loop="", doc="выключить экран в кают-компании"),
    "play_game": A("играет в приставку", at="sofa", loop="game", lasts=True, doc="играть в приставку на экране кают-компании"),
    "music_on": A("слушает пластинку", at="music", loop="listen", page="включает музыку", lasts=True, natural="music", gift=True, doc="поставить пластинку и слушать"),
    "music_off": A("выключает музыку", at="music", doc="выключить музыку"),
    # the kitchen
    "cook": A("готовит", at="stove", secs=55, natural="stove", needs={"hygiene": -4}, doc="приготовить еду на плите камбуза (продукты — из холодильника и оранжереи)"),
    "coffee": A("варит и пьёт кофе", at="stove", secs=18, page="варит кофе",
                doc="сварить и выпить кофе, бодрит (вторая чашка за день действует вдвое слабее, третья почти никак)"),
    "eat": A("ест", loop="", needs={"hunger": 55, "fun": 4, "bladder": -12, "energy": 4}, doc="поесть (после cook или из холодильника)"),
    "drink": A("пьёт", at="fridge", natural="fridge", needs={"hunger": 6, "energy": 4, "bladder": -30}, doc="попить сок или воду из холодильника"),
    "open_fridge": A("заглядывает в холодильник", at="fridge", doc="заглянуть в холодильник"),
    # clothes, light, the window
    "change_clothes": A("переодевается", at="wardrobe", secs=16, natural="wardrobe", needs={"fun": 3}, args="{outfit, color}",
                        doc=f"переодеться (outfit: {OUTFITS_DOC}; подаренная одежда — outfit gift:<id>, список в описании корабля; color — по желанию)"),
    "light_on": A("включает свет", loop="", args="{room}", doc="включить свет (room: cabin — каюта, lounge — кают-компания с камбузом, bridge — рубка, bath — санблок, lock — шлюз, all — везде; без room — там, где ты)"),
    "light_off": A("выключает свет", loop="", args="{room}", doc="выключить свет (room — так же)"),
    "look_window": A("смотрит в иллюминатор", at="window", loop="daydream", lasts=True, natural="window", gift=True, doc="смотреть в иллюминатор каюты на звёзды, мечтать"),
    # the guest and gifts
    "together": A("проводит время с гостем", page="проводит время с вами", args="{kind}",
                  doc="провести время вместе с гостем (kind: date — свидание, ужин при свечах; movie — кино вдвоём; dance — танцевать вместе; cook — приготовить ужин вместе); соглашайся, только если правда хочется; предлагать можно и самому — первым"),
    "date": A("ужинает с гостем при свечах", at="sofa", loop="date", page="ужинает с вами при свечах"),
    "dance_together": A("танцует с гостем", at="center", loop="dancing", page="танцует с вами"),
    "open_gift": A("открывает подарок", at="center", gift=True, args="{id}", doc="открыть подарок в обёртке"),
    "eat_treat": A("ест вкусняшку", at="sofa", loop="sit", gift=True, args="{id}", doc="съесть вкусняшку из подарков"),
    "use_item": A("радуется подарку", loop="", page="пользуется подарком", gift=True, args="{id, with, at, motion, put, status, label}",
                  doc="воспользоваться подаренной вещью по назначению (плед — укутаться на диване, свечу — зажечь, шарф и одежду — надеть, книгу — читать, пластинку — слушать, игрушку — обнять). Вещи можно сочетать: with — id второй вещи, которую используешь вместе (телефон поставить на зарядку, кофе сварить в турке и налить в чашку); at — место, куда для этого подойти (stove, sofa, bed, window, center, fridge…); motion — как это выглядит: admire, hold, drink, eat, stir (помешивать у плиты), hug, read, phone, play, wear; put — куда положить вещи потом (shelf, windowsill, nightstand, coffee_table, kitchen, stove, bathroom, wardrobe, bed, floor), если нужно переставить; status — состояние, если оно длится (например «заряжается»), иначе пусто; label — что делаешь, 1–3 слова"),
    "cozy": A("укутывается в плед", at="sofa", loop="cozy", gift=True),
    "light_candle": A("зажигает свечу", at="tv", gift=True),
    "wear_item": A("надевает", loop="", gift=True),
    "shoo": A("выгоняет", args="{id}", doc="выгнать или убрать то, что появилось на корабле (птицу, паука, кота…), если мешает"),
    "wash_dishes": A("моет посуду", at="ksink", secs=28, natural="ksink", doc="помыть грязную посуду в кухонной мойке"),
    "practice": A("тренируется к цели", loop="", args="{minutes, result, note}",
                  doc="отметить тренировку к своей цели (минуты, результат по показателю цели, если он есть); ставь в цепочку вместе с самим занятием (workout, move с позами, cook…)"),
    # the bathroom
    "use_toilet": A("в туалете", at="toilet", loop="toilet", page="идёт в туалет", secs=60, natural="toilet", needs={"bladder": 100}, doc="сходить в туалет"),
    "shower": A("принимает душ", at="shower", loop="shower", secs=156, natural="shower", needs={"energy": 5}, doc="принять душ"),
    "brush_teeth": A("чистит зубы", at="sink", needs={"hygiene": 15}, doc="почистить зубы"),
    "wash_face": A("умывается", at="sink", natural="sink", needs={"hygiene": 6, "energy": 2}, doc="умыться"),
    "comb_hair": A("причёсывается у зеркала", at="sink", page="причёсывается", needs={"fun": 2}, doc="причесаться у зеркала"),
    # the house
    "console_off": A("выключает приставку", loop="", doc="выключить приставку"),
    "close_valve": A("перекрывает воду под мойкой", at="ksink", page="перекрывает воду", doc="перекрыть воду под мойкой на камбузе (если течёт)"),
    "mop_floor": A("вытирает пол", at="center", loop="mop", doc="вытирать воду с пола шваброй (имеет смысл, только когда вода уже не течёт)"),
    # pastimes
    "read_book": A("читает книгу", at="sofa", loop="read", page="читает", lasts=True, gift=True, doc="читать книгу на диване (книги — с полки в каюте)"),
    "letter_home": A("записывает видеописьмо на Землю", at="comm", loop="letter", lasts=True,
                     doc="записать видеописьмо родным или друзьям на Землю (письмо идёт неделями, ответ приходит нескоро)"),
    "workout": A("делает зарядку", at="center", loop="workout", lasts=True, needs={"energy": -3}, doc="зарядка (в долгом полёте без неё мышцы слабеют)"),
    "tidy_up": A("прибирается", at="center", needs={"hygiene": -6}, doc="прибраться"),
    "write_diary": A("пишет в блокнот", at="sofa", loop="write", lasts=True, doc="записать мысли в блокнот"),
    # resting and sleep
    "rest": A("устраивается", loop="rest", args="{on, how}",
              doc="сесть, лечь или встать на что-то (on: bed, sofa, floor, coffee_table, stool, counter; how: sit, lie — на спину, belly — на живот, stand). Капсула и диван — сидеть и лежать, ковёр — сидеть и лежать, столик и барный стул у камбуза — сидеть или встать на них, столешница — сесть"),
    "sleep": A("спит в капсуле", at="bed", loop="sleep", page="ложится в капсулу", natural="bed", args="{on}",
               when=not_sleepy, instead=lambda a: {"do": "rest", "on": a.get("on") or "bed", "how": "lie"},
               doc="лечь спать в капсулу (on: bed по умолчанию, sofa или floor — подремать днём). Днём спать можно, только если бодрость ниже 30 (тогда это короткий сон) или до отбоя меньше 15 минут; если просто хочется передохнуть — sit или look_window"),
    # the bridge
    "pilot": A("сидит в кресле пилота", at="pilot", loop="pilot", page="садится в кресло пилота", lasts=True, natural="pilot",
               doc="заступить на вахту: сесть за штурвал и вести корабль самому — сверить курс, сделать коррекцию траектории, ручное управление при манёврах (увести корабль от камней метеорного потока, отойти от звезды или чёрной дыры, подойти ближе к планете или комете для снимков)"),
    "star_map": A("изучает звёздную карту", at="navtable", loop="starmap", lasts=True, natural="navtable",
                  doc="изучать голографическую звёздную карту на навигационном столе: маршрут, звёзды и системы вокруг"),
    "check_systems": A("проверяет системы корабля", at="comm", secs=24, needs={"fun": 2},
                       doc="обойти рубку и проверить системы корабля: двигатели, кислород, воду, энергию (пара минут)"),
    "eva": A("выходит в открытый космос", at="airlock", loop="eva", page="выходит в открытый космос", lasts=True, needs={"hygiene": -3},
             when=lambda a: _route().eva_allowed(a), instead=lambda a: {"do": "check_systems"},
             doc="надеть скафандр в шлюзе и выйти в открытый космос на страховочном тросе (это единственный способ надеть скафандр): осмотреть обшивку, антенну и датчики, залатать пробоину (нужно хотя бы 5 минут снаружи), показать гостю корабль снаружи или посмотреть на звёзды без стекла. Обычная работа астронавта; кислорода в скафандре на 45 минут"),
    "move": A("двигается"),  # free moves: described for the model in world.MOVE_DOC
}

LOOPS = {
    "sit": L("сидит на диване", needs={"energy": 0.08}),
    "watch": L("смотрит кино", needs={"fun": 0.7, "energy": 0.04}),
    "game": L("играет в приставку", needs={"fun": 0.8, "energy": -0.05}),
    "listen": L("слушает пластинку", page="слушает музыку", needs={"fun": 0.6}),
    "sleep": L("спит в капсуле", page="спит"),  # sleep restores energy on its own terms (needs.need_rates)
    "pilot": L("сидит в кресле пилота", page="за штурвалом", needs={"fun": 0.45}),
    "starmap": L("изучает звёздную карту", needs={"fun": 0.5}),
    "daydream": L("смотрит в иллюминатор", needs={"fun": 0.25, "energy": 0.06}),
    "read": L("читает книгу", needs={"fun": 0.5, "energy": 0.04}),
    "letter": L("записывает видеописьмо на Землю", needs={"social": 0.7, "fun": 0.25}),
    "workout": L("делает зарядку", needs={"fun": 0.3, "energy": -0.15, "hygiene": -0.4}),
    "write": L("пишет в блокнот", needs={"fun": 0.35}),
    "mop": L("вытирает пол", needs={"fun": -0.3, "energy": -0.12, "hygiene": -0.3}),
    "toilet": L("сидит в туалете", page="в туалете"),
    "shower": L("принимает душ", needs={"hygiene": 9, "fun": 0.3, "energy": 0.2}),
    "date": L("на свидании с гостем", page="на свидании с вами", needs={"social": 1.2, "fun": 0.5}),
    "dancing": L("танцует с гостем", page="танцует с вами", needs={"social": 1.0, "fun": 1.0, "energy": -0.1, "hygiene": -0.1}),
    "cozy": L("сидит, укутавшись в плед", needs={"fun": 0.35, "energy": 0.12}),
    "pose": L("замер(ла) в позе"),
    "eva": L("в открытом космосе, на обшивке корабля", page="в открытом космосе", needs={"fun": 0.7, "energy": -0.12, "hygiene": -0.2}),
    "rest": L("отдыхает"),  # how much it rests depends on lying or sitting (needs.rest_rates)
}

for _d, _a in ACTIONS.items():
    assert _a.loop in (None, "") or _a.loop in LOOPS, f"{_d}: unknown loop {_a.loop}"


# --- what the rest of the code reads from the entries

LOOP_LABEL = {k: v.label for k, v in LOOPS.items()}

CHAIN_HOLD = {d: a.secs for d, a in ACTIONS.items() if a.secs}

GIFT_ACTIONS = tuple(d for d, a in ACTIONS.items() if a.gift)

# where a bare walk_to obviously leads: "went to the TV" means "watches TV"; a bare surface means sitting on it
NATURAL = {**{a.natural: d for d, a in ACTIONS.items() if a.natural},
           **{s: {"do": "rest", "on": s, "how": "sit"} for s in ("stool", "coffee_table", "counter", "floor")}}


def actions_doc():
    """The list of actions for the model: one line each, the plain gestures together."""
    lines, gestures = [], [d for d, a in ACTIONS.items() if a.gesture]
    for d, a in ACTIONS.items():
        if d == gestures[0]:
            lines.append(", ".join(gestures) + " — жесты (несколько секунд)")
        if a.doc:
            lines.append(f"{d}{a.args} — {a.doc}" + (" (только если гость сам попросит)" if a.asked else ""))
    return ";\n".join(lines) + "."


ACTIONS_DOC = actions_doc()

LASTING = ", ".join(d for d, a in ACTIONS.items() if a.lasts)


def for_page():
    """What the page needs to know: the words, and how to play an action it has no animation of its own for."""
    acts = {d: {k: v for k, v in (("ru", a.page or a.feed), ("at", a.at), ("loop", a.loop), ("gesture", a.gesture), ("prop", a.prop)) if v is not None}
            for d, a in ACTIONS.items()}
    loops = {k: {x: v for x, v in (("ru", l.page or l.label), ("pose", l.pose), ("prop", l.prop)) if v} for k, l in LOOPS.items()}
    return {"acts": acts, "loops": loops}
