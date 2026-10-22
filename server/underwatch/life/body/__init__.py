"""The body: what the resident does. plan.py reads the model's chain of actions, act.py carries it out,
and each theme of actions has its own module (devices, clothes, hygiene, kitchen, rest, house, moves, company)."""
# what the rest of life calls: body.act(actions) and body.understand(raw)
from .act import act
from .plan import understand
