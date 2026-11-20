"""The ship «Странник»: places, compartments, furniture, clothes; what the body can do is in catalog.py."""



PLACES = {
    "bed": "капсула для сна в каюте", "window": "иллюминатор в каюте", "wardrobe": "шкафчик с одеждой в каюте", "sofa": "диван в кают-компании",
    "tv": "экран в кают-компании", "music": "проигрыватель пластинок", "fridge": "холодильник на камбузе", "stove": "плита на камбузе",
    "center": "середина кают-компании", "toilet": "туалет в санблоке", "sink": "раковина в санблоке", "shower": "душевая капсула",
    "ksink": "мойка на камбузе", "coffee_table": "столик у дивана", "stool": "барный стул у камбуза", "counter": "столешница камбуза",
    "floor": "ковёр в кают-компании", "pilot": "кресло пилота в рубке", "navtable": "навигационный стол в рубке",
    "comm": "главный экран рубки (связь)", "airlock": "шлюз со скафандром",
}

# anything with a surface can be sat, lain or stood on, if there is room
SURFACES = {"bed": ("sit", "lie", "belly"), "sofa": ("sit", "lie", "belly"), "floor": ("sit", "lie", "belly"), "coffee_table": ("sit", "stand"),
            "stool": ("sit", "stand"), "counter": ("sit",)}

HOW_RU = {"sit": ("сидит на", "сидит"), "lie": ("лежит на", "лежит"), "belly": ("лежит на животе на", "лежит на животе"), "stand": ("стоит на", "стоит")}

SURF_RU = {"bed": "капсуле", "sofa": "диване", "floor": "ковре", "coffee_table": "столике", "stool": "барном стуле", "counter": "столешнице"}

OUTFIT_TYPES = {"casual": "футболка и брюки", "pajamas": "пижама", "dress": "романтичное платье", "shorts": "шорты и футболка",
                "warm": "джинсы и свитер", "mini": "миниюбка и топ", "swimsuit": "купальник", "underwear": "нижнее бельё",
                "bathrobe": "халат", "towel": "полотенце", "nude": "голое тело"}

COLORS = {"red": "красное", "blue": "синее", "green": "зелёное", "yellow": "жёлтое", "purple": "фиолетовое",
          "orange": "оранжевое", "pink": "розовое", "black": "чёрное", "white": "белое"}

# where a drawn thing can stand (the page knows the coordinates)
SPOTS = {"shelf": "полка под экраном в кают-компании (книги, сувениры, мелочи)", "windowsill": "книжная полка под иллюминатором в каюте (цветы, растения, свечи, фигурки)",
         "nightstand": "полочка в нише капсулы (телефон, часы, зарядка, книга на ночь)", "coffee_table": "столик у дивана (еда, напитки, журналы)",
         "kitchen": "столешница камбуза и холодильник (посуда, турка, продукты)", "stove": "у плиты на камбузе (турка, кастрюлька, сковорода)",
         "bathroom": "санблок (косметика, щётки, полотенца)", "wardrobe": "на шкафчике в каюте (коробки, шляпы, сумки)",
         "bed": "в капсуле (подушки, игрушки)", "bridge": "пульт в рубке (талисманы, фигурки, фото)",
         "floor": "на полу в кают-компании (что покрупнее: гитара, гантели, растение в горшке)"}

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

# things every resident has from the start (the ship is the same for everyone; gifts come on top)
HOUSEHOLD = {"turka": "медная турка у плиты на камбузе", "cups": "чашки на полке камбуза"}

# the ship's compartments and their lamps
ROOMS = {"cabin": ("cabin", "night"), "lounge": ("lounge", "galley"), "bridge": ("bridge",), "bath": ("bath",), "lock": ("lock",),
         "all": ("cabin", "night", "lounge", "galley", "bridge", "bath", "lock")}

LAMP_RU = {"cabin": "свет в каюте", "night": "подсветка капсулы", "lounge": "свет в кают-компании", "galley": "свет на камбузе",
           "bridge": "свет в рубке", "bath": "свет в санблоке", "lock": "свет в шлюзе"}

WATER_MAX, WATER_RISE, MOP_RATE = 5.0, 10.0, 1.0  # cm; cm/min while leaking; cm/min while mopping

MOVE_RANGES = {"torso": (-45, 120), "head": (-45, 50), "turn": (-1, 1), "shoulder_near": (-60, 190), "shoulder_far": (-60, 190),
               "elbow_near": (0, 160), "elbow_far": (0, 160), "hip_near": (-120, 130), "hip_far": (-120, 130),
               "knee_near": (0, 160), "knee_far": (0, 160), "tilt": (-95, 100), "dx": (-80, 80), "t": (0.2, 5), "hold": (0, 20)}

TOGETHER = {"date": "свидание: ужин при свечах", "movie": "кино вдвоём", "dance": "танцы вместе", "cook": "приготовить ужин вместе", "custom": "своё занятие вдвоём"}

TOGETHER_LOOPS = {"date": ("date",), "movie": ("watch", "sit"), "dance": ("dancing", "listen"), "cook": ("date",), "custom": ("date", "sit", "rest", "pose")}


ROOM_OF = {"bed": "cabin", "window": "cabin", "wardrobe": "cabin", "toilet": "bath", "sink": "bath", "shower": "bath",
           "pilot": "bridge", "navtable": "bridge", "comm": "bridge", "airlock": "lock"}

ROOM_RU = {"cabin": "каюта", "lounge": "кают-компания", "bridge": "рубка", "bath": "санблок", "lock": "шлюз"}


def room_of(loc):
    return ROOM_OF.get(loc, "lounge")


def room_ru(room):
    return ROOM_RU[room]
