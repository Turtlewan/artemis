"""Built-in reaction recipe wiring."""

from artemis.reactions.recipes.comms import register_comms_reactions
from artemis.reactions.recipes.planning import register_planning_reactions
from artemis.reactions.recipes.self import register_self_reactions

__all__ = ["register_comms_reactions", "register_planning_reactions", "register_self_reactions"]
