"""delete rules on foreign keys

Deleting an account left its events behind, and deleting a recipe left its
favorites (and meal-plan days pointing at nothing). Now:
- event.account_id         ON DELETE CASCADE   (cached events go with the account)
- recipefavorite.recipe_id ON DELETE CASCADE
- mealplan.recipe_id       ON DELETE SET NULL  (the day stays, unassigned)

SQLite can't alter a foreign key in place, so batch mode rebuilds each table
(copying its rows across). SQLite also stores these constraints unnamed, so
each one is given a name from NAMING while being rebuilt, dropped by that
name, and re-created with its delete rule.

Revision ID: 1b3fe1eb0fe1
Revises: 851ee972b24c
Create Date: 2026-09-23 22:05:25.150838
"""

from typing import Sequence, Union

import sqlalchemy as sa  # noqa: F401
import sqlmodel  # noqa: F401  autogenerate renders SQLModel's string type as sqlmodel.sql.sqltypes.AutoString
from alembic import op

revision: str = "1b3fe1eb0fe1"
down_revision: Union[str, Sequence[str], None] = "851ee972b24c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}

# (table, column, referred table, delete rule)
RULES = [
    ("event", "account_id", "account", "CASCADE"),
    ("mealplan", "recipe_id", "recipe", "SET NULL"),
    ("recipefavorite", "recipe_id", "recipe", "CASCADE"),
]


def _set_rule(table: str, column: str, referred: str, ondelete) -> None:
    name = f"fk_{table}_{column}_{referred}"
    with op.batch_alter_table(table, naming_convention=NAMING) as batch_op:
        batch_op.drop_constraint(name, type_="foreignkey")
        batch_op.create_foreign_key(name, referred, [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    for table, column, referred, rule in RULES:
        _set_rule(table, column, referred, rule)


def downgrade() -> None:
    for table, column, referred, _rule in RULES:
        _set_rule(table, column, referred, None)
