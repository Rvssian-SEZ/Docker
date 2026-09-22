defmodule Coffer.Repo.Migrations.AddPositionToBudgetCategories do
  use Ecto.Migration

  def up do
    alter table(:budget_categories) do
      add :position, :integer
    end

    # Backfills existing rows with their current alphabetical order as a
    # starting position, scoped per sibling group (same parent_id) -- so
    # the custom order starts out identical to today's display order and
    # only diverges once someone actually reorders something.
    execute """
    UPDATE budget_categories AS c
    SET position = ranked.rn
    FROM (
      SELECT id, ROW_NUMBER() OVER (PARTITION BY parent_id ORDER BY name) - 1 AS rn
      FROM budget_categories
    ) AS ranked
    WHERE c.id = ranked.id
    """

    alter table(:budget_categories) do
      modify :position, :integer, null: false
    end
  end

  def down do
    alter table(:budget_categories) do
      remove :position
    end
  end
end
