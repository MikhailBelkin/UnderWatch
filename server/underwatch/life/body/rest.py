"""Sitting, lying and sleeping on any surface, and waking up."""
from ...context import S


def rest(a, body):
    """Sits, lies on the back or the stomach, or stands on a surface: a["on"] (bed, sofa, floor…), a["how"]."""
    body.loc, body.loop = a["on"], "rest"
    S["rest"] = {"on": a["on"], "how": a["how"]}


def sleep(a, body):
    """Goes to sleep (in bed, or a nap on the sofa or the floor): everything is switched off, the lights too."""
    body.loc = a.get("on") or "bed"
    S["rest"] = {"on": body.loc, "how": "lie"}
    S.update(tv="off", music=False, console=False)
    S["lights"] = {k: False for k in S["lights"]}
    S["accessory"] = None


def after_chain(actions, body):
    """Waking up: the bedroom light goes on."""
    if body.was_sleeping and body.loop != "sleep":
        S["lights"]["bed"] = True


EFFECTS = {"rest": rest, "sleep": sleep}
