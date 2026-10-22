"""Free moves: poses the model composes from joint angles (plank, push-ups, an arabesque…)."""
from ...context import S
from .. import needs


def move(a, body):
    """Tires her a little by how long it lasts, amuses her a little. "end": "hold" freezes her in the last pose;
    "on" (bed, sofa, table) is the surface the body rests on instead of the floor."""
    effort = a.get("secs", 0) / 10
    S["needs"]["energy"] = needs.clampn(S["needs"]["energy"] - 0.8 * effort)
    S["needs"]["hygiene"] = needs.clampn(S["needs"]["hygiene"] - 0.4 * effort)
    S["needs"]["fun"] = needs.clampn(S["needs"]["fun"] + needs.fun_gain(2))
    if a.get("end") == "hold":
        body.loop = "pose"
        S["pose_hold"] = {"frame": a["frames"][-1], "label": a.get("label", ""), "on": a.get("on", "floor")}
        if a.get("on") and a["on"] != "floor":
            body.loc = a["on"]


EFFECTS = {"move": move}
