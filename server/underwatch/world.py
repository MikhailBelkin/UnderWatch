"""The flat: places, rooms, furniture, and everything the body can do."""



PLACES = {
    "bed": "кровать", "window": "окно", "wardrobe": "шкаф", "sofa": "диван", "tv": "телевизор",
    "music": "проигрыватель", "fridge": "холодильник", "stove": "плита", "center": "середина комнаты",
    "toilet": "унитаз", "sink": "раковина", "shower": "душ", "ksink": "кухонная мойка",
    "coffee_table": "журнальный столик", "stool": "барный стул", "counter": "кухонная столешница", "floor": "ковёр на полу",
}

# anything with a surface can be sat, lain or stood on, if there is room
SURFACES = {"bed": ("sit", "lie", "belly"), "sofa": ("sit", "lie", "belly"), "floor": ("sit", "lie", "belly"), "coffee_table": ("sit", "stand"),
            "stool": ("sit", "stand"), "counter": ("sit",)}

HOW_RU = {"sit": ("сидит на", "сидит"), "lie": ("лежит на", "лежит"), "belly": ("лежит на животе на", "лежит на животе"), "stand": ("стоит на", "стоит")}

SURF_RU = {"bed": "кровати", "sofa": "диване", "floor": "ковре", "coffee_table": "журнальном столике", "stool": "барном стуле", "counter": "столешнице"}

OUTFIT_TYPES = {"casual": "футболка и брюки", "pajamas": "пижама", "dress": "романтичное платье", "shorts": "шорты и футболка",
                "warm": "джинсы и свитер", "mini": "миниюбка и топ", "swimsuit": "купальник", "underwear": "нижнее бельё",
                "bathrobe": "халат", "towel": "полотенце"}

COLORS = {"red": "красное", "blue": "синее", "green": "зелёное", "yellow": "жёлтое", "purple": "фиолетовое",
          "orange": "оранжевое", "pink": "розовое", "black": "чёрное", "white": "белое"}

# do -> (place it happens at, loop it leaves the body in, label)
ACTIONS = {
    "walk_to": (None, None, "идёт"), "wave": (None, "", "машет"), "nod": (None, "", "кивает"),
    "shake_head": (None, "", "мотает головой"), "shrug": (None, "", "пожимает плечами"), "jump": (None, None, "прыгает"),
    "dance": (None, None, "танцует"), "think": (None, "", "думает"), "laugh": (None, "", "смеётся"),
    "bow": (None, "", "кланяется"), "stretch": (None, None, "потягивается"), "sit": ("sofa", "sit", "сидит на диване"),
    "stand": (None, None, "встаёт"), "watch_tv": ("sofa", "watch", "смотрит телевизор"),
    "open_gift": ("center", None, "открывает подарок"), "eat_treat": ("sofa", "sit", "ест вкусняшку"),
    "use_item": (None, "", "радуется подарку"), "shoo": (None, None, "выгоняет"), "practice": (None, "", "тренируется к цели"), "together": (None, None, "проводит время с гостем"),
    "cozy": ("sofa", "cozy", "укутывается в плед"), "move": (None, None, "двигается"), "rest": (None, "rest", "устраивается"), "light_candle": ("tv", None, "зажигает свечу"), "wear_item": (None, "", "надевает"),
    "date": ("sofa", "date", "ужинает с гостем при свечах"), "dance_together": ("center", "dancing", "танцует с гостем"),
    "tv_off": (None, "", "выключает телевизор"), "play_game": ("sofa", "game", "играет в приставку"),
    "music_on": ("music", "listen", "слушает пластинку"), "music_off": ("music", None, "выключает музыку"),
    "cook": ("stove", None, "готовит"), "eat": (None, "", "ест"), "drink": ("fridge", None, "пьёт"),
    "open_fridge": ("fridge", None, "заглядывает в холодильник"), "sleep": ("bed", "sleep", "спит"),
    "change_clothes": ("wardrobe", None, "переодевается"), "light_on": (None, "", "включает свет"),
    "light_off": (None, "", "выключает свет"), "look_window": ("window", "daydream", "смотрит в окно"),
    "read_book": ("sofa", "read", "читает книгу"), "phone_call": ("window", "phone", "болтает по телефону"),
    "workout": ("center", "workout", "делает зарядку"), "tidy_up": ("center", None, "прибирается"),
    "write_diary": ("sofa", "write", "пишет в блокнот"), "console_off": (None, "", "выключает приставку"),
    "close_valve": ("stove", None, "перекрывает воду под мойкой"), "mop_floor": ("center", "mop", "вытирает пол"),
    "use_toilet": ("toilet", "toilet", "в туалете"), "shower": ("shower", "shower", "принимает душ"),
    "brush_teeth": ("sink", None, "чистит зубы"), "wash_face": ("sink", None, "умывается"),
    "comb_hair": ("sink", None, "причёсывается у зеркала"), "wash_dishes": ("ksink", None, "моет посуду"),
}

# where a drawn thing can stand (the page knows the coordinates)
SPOTS = {"shelf": "полка над телевизором (книги, сувениры, мелочи)", "windowsill": "подоконник в спальне (цветы, растения, свечи, птицы)",
         "nightstand": "тумбочка у кровати (телефон, часы, зарядка, книга на ночь)", "coffee_table": "журнальный столик у дивана (еда, напитки, журналы)",
         "kitchen": "кухонная столешница и холодильник (посуда, турка, продукты)", "stove": "у плиты (турка, кастрюлька, сковорода)",
         "bathroom": "санузел (косметика, щётки, полотенца)", "wardrobe": "на шкафу (коробки, шляпы, сумки)",
         "bed": "на кровати (подушки, игрушки)", "floor": "на полу в гостиной (что покрупнее: гитара, гантели, растение в горшке)"}

MOTIONS = ("admire", "hold", "drink", "eat", "stir", "hug", "read", "phone", "play", "wear")

MOVE_DOC = """move — любое движение, которого нет в списке: ты сам(а) описываешь ключевые позы тела, тело плавно переходит из одной в другую.
{"do": "move", "label": "что делаешь, 1–3 слова", "frames": [поза, ...], "repeat": сколько раз повторить кадры (1–10), "end": "stand" (потом встать) или "hold" (замереть в последней позе), "on": "на чём: floor (по умолчанию), bed, sofa, coffee_table — тело опирается на эту поверхность"}
Поза — углы в градусах (вид сбоку, ты смотришь вперёд), любые поля можно опустить (тогда 0):
  torso: наклон корпуса от бёдер, + вперёд (90 — согнуться пополам), − назад (до −40);
  head: наклон головы, + вниз, − вверх (−45…50); turn: поворот головы −1…1 (покрутить головой — чередуй −1 и 1);
  shoulder_near / shoulder_far: рука от корпуса — 0 вдоль тела вниз, 90 вперёд, 180 вверх, −50 назад;
  elbow_near / elbow_far: сгиб локтя 0…150 (кисть идёт вперёд и вверх; руки к голове — плечо ~150, локоть ~110);
  hip_near / hip_far: бедро от вертикали — 0 вниз, 90 вперёд-горизонтально (сидя), −90 назад-горизонтально (ласточка);
  knee_near / knee_far: сгиб колена 0…150 (голень уходит назад);
  tilt: наклон всего тела — 0 стоя, 80–90 горизонтально лицом вниз (планка, ползти), −90 лёжа на спине;
  dx: сдвиг вперёд в пикселях от начального места (−80…80), чтобы ползти или шагать;
  t: секунды на переход в эту позу (0.2–5); hold: сколько держать позу, секунд (0–20).
Тело само опускается на пол той точкой, что ниже всех (стопы, колени, ладони, попа) — высоту указывать не нужно.
Примеры: планка — {"tilt":78,"shoulder_near":90,"shoulder_far":90,"t":1.5,"hold":15};
отжимание — кадры {"tilt":75,"shoulder_near":90,"shoulder_far":90,"t":0.6} и {"tilt":85,"shoulder_near":55,"shoulder_far":55,"elbow_near":110,"elbow_far":110,"t":0.6}, repeat 5;
на четвереньках — {"tilt":82,"hip_near":95,"hip_far":95,"knee_near":95,"knee_far":95,"shoulder_near":95,"shoulder_far":95};
схватиться за голову — {"shoulder_near":150,"shoulder_far":150,"elbow_near":115,"elbow_far":115,"head":10}; ласточка — {"torso":85,"hip_far":-90,"shoulder_near":160,"shoulder_far":160,"hold":4}."""

ACTIONS_DOC = """walk_to{place} — пойти к месту; wave, nod, shake_head, shrug, jump, dance, think, laugh, bow, stretch — жесты (несколько секунд);
sit — сесть на диван (сесть на что-то другое — rest{on, sit}, например rest{stool, sit} — на барный стул); stand — встать; watch_tv — сесть и смотреть телевизор; tv_off — выключить телевизор;
play_game — играть в приставку; music_on — поставить пластинку и слушать; music_off — выключить музыку;
cook — приготовить еду на плите; eat — поесть (после cook или из холодильника); drink — попить из холодильника; open_fridge — заглянуть в холодильник;
change_clothes{outfit, color} — переодеться (outfit: casual — футболка и брюки, pajamas — пижама, dress — романтичное платье, shorts — шорты и футболка, warm — джинсы и свитер, mini — миниюбка и топ, swimsuit — купальник, underwear — нижнее бельё, bathrobe — халат, towel — полотенце; подаренная одежда — outfit gift:<id>, список в описании квартиры; color — по желанию); light_on{room} / light_off{room} — свет (room: bedroom, living, kitchen, bathroom, all; без room — там, где ты); look_window — смотреть в окно, мечтать;
together{kind} — провести время вместе с гостем (kind: date — свидание, ужин при свечах; movie — кино вдвоём; dance — танцевать вместе; cook — приготовить ужин вместе); соглашайся, только если правда хочется; предлагать можно и самому — первым;
open_gift{id} — открыть подарок в обёртке; eat_treat{id} — съесть вкусняшку из подарков; use_item{id, with, at, motion, put, status, label} — воспользоваться подаренной вещью по назначению (плед — укутаться на диване, свечу — зажечь, шарф и одежду — надеть, книгу — читать, пластинку — слушать, игрушку — обнять). Вещи можно сочетать: with — id второй вещи, которую используешь вместе (телефон поставить на зарядку, кофе сварить в турке и налить в чашку); at — место, куда для этого подойти (stove, sofa, bed, window, center, fridge…); motion — как это выглядит: admire, hold, drink, eat, stir (помешивать у плиты), hug, read, phone, play, wear; put — куда положить вещи потом (shelf, windowsill, nightstand, coffee_table, kitchen, stove, bathroom, wardrobe, bed, floor), если нужно переставить; status — состояние, если оно длится (например «заряжается»), иначе пусто; label — что делаешь, 1–3 слова;
shoo{id} — выгнать или убрать то, что появилось в квартире (птицу, паука, кота…), если мешает;
wash_dishes — помыть грязную посуду в кухонной мойке;
practice{minutes, result, note} — отметить тренировку к своей цели (минуты, результат по показателю цели, если он есть); ставь в цепочку вместе с самим занятием (workout, move с позами, cook…);
use_toilet — сходить в туалет; shower — принять душ; brush_teeth — почистить зубы; wash_face — умыться; comb_hair — причесаться у зеркала;
console_off — выключить приставку; close_valve — перекрыть воду под мойкой (если течёт); mop_floor — вытирать воду с пола шваброй (имеет смысл, только когда вода уже не течёт);
read_book — читать книгу на диване; phone_call — позвонить кому-то из друзей или родных; workout — зарядка;
tidy_up — прибраться; write_diary — записать мысли в блокнот; rest{on, how} — сесть, лечь или встать на что-то (on: bed, sofa, floor, coffee_table, stool, counter; how: sit, lie — на спину, belly — на живот, stand). Кровать и диван — сидеть и лежать, пол/ковёр — сидеть и лежать, журнальный столик и барный стул на кухне — сидеть или встать на них, столешница — сесть;
sleep{on} — лечь спать (on: bed по умолчанию, sofa или floor — подремать днём). Днём спать можно, только если бодрость ниже 30 (тогда это короткий сон) или до отбоя меньше 15 минут; если просто хочется передохнуть — sit или look_window."""

LOOP_LABEL = {"sit": "сидит на диване", "watch": "смотрит телевизор", "game": "играет в приставку", "listen": "слушает пластинку",
              "sleep": "спит", "daydream": "смотрит в окно", "read": "читает книгу", "phone": "болтает по телефону",
              "workout": "делает зарядку", "write": "пишет в блокнот", "mop": "вытирает пол", "toilet": "сидит в туалете", "shower": "принимает душ",
              "date": "на свидании с гостем", "dancing": "танцует с гостем", "cozy": "сидит, укутавшись в плед", "pose": "замер(ла) в позе", "rest": "отдыхает"}

ROOMS = {"bedroom": ("bed", "night"), "living": ("liv", "floor"), "kitchen": ("kit",), "bathroom": ("bath",),
         "all": ("bed", "night", "liv", "floor", "kit", "bath")}

LAMP_RU = {"bed": "свет в спальне", "night": "ночник", "liv": "свет в гостиной", "floor": "торшер", "kit": "свет на кухне", "bath": "свет в ванной"}

WATER_MAX, WATER_RISE, MOP_RATE = 5.0, 10.0, 1.0  # cm; cm/min while leaking; cm/min while mopping

MOVE_RANGES = {"torso": (-45, 120), "head": (-45, 50), "turn": (-1, 1), "shoulder_near": (-60, 190), "shoulder_far": (-60, 190),
               "elbow_near": (0, 160), "elbow_far": (0, 160), "hip_near": (-120, 130), "hip_far": (-120, 130),
               "knee_near": (0, 160), "knee_far": (0, 160), "tilt": (-95, 100), "dx": (-80, 80), "t": (0.2, 5), "hold": (0, 20)}

# where a bare walk_to obviously leads: "went to the TV" means "watches TV"
NATURAL = {"tv": "watch_tv", "sofa": "sit", "music": "music_on", "stove": "cook", "fridge": "drink",
           "window": "look_window", "wardrobe": "change_clothes", "bed": "sleep", "toilet": "use_toilet", "sink": "wash_face", "shower": "shower", "ksink": "wash_dishes",
           "stool": {"do": "rest", "on": "stool", "how": "sit"}, "coffee_table": {"do": "rest", "on": "coffee_table", "how": "sit"},
           "counter": {"do": "rest", "on": "counter", "how": "sit"}, "floor": {"do": "rest", "on": "floor", "how": "sit"}}

CHAIN_HOLD = {"use_toilet": 60, "shower": 156, "change_clothes": 16, "cook": 55, "wash_dishes": 28}  # seconds these take for the body

TOGETHER = {"date": "свидание: ужин при свечах", "movie": "кино вдвоём", "dance": "танцы вместе", "cook": "приготовить ужин вместе", "custom": "своё занятие вдвоём"}

TOGETHER_LOOPS = {"date": ("date",), "movie": ("watch", "sit"), "dance": ("dancing", "listen"), "cook": ("date",), "custom": ("date", "sit", "rest", "pose")}


def room_of(loc):
    if loc in ("toilet", "sink", "shower"):
        return "bathroom"
    if loc in ("stool", "counter", "ksink"):
        return "kitchen"
    return "bedroom" if loc in ("bed", "window", "wardrobe") else "kitchen" if loc in ("fridge", "stove") else "living"


def room_ru(room):
    return {"bedroom": "спальня", "living": "гостиная", "kitchen": "кухня", "bathroom": "санузел"}[room]
