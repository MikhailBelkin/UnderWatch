"""The body: what the resident does. plan.py reads the model's chain of actions, act.py carries it out,
and each theme of actions has its own module (devices, clothes, hygiene, kitchen, rest, house, moves, company)."""
from .act import act
from .plan import body_allows, clean_actions, clean_move, complete_chain, resolve_together, understand
