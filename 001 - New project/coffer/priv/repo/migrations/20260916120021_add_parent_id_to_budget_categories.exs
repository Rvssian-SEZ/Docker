defmodule Coffer.Repo.Migrations.AddParentIdToBudgetCategories do
  use Ecto.Migration

  def change do
    alter table(:budget_categories) do
      add :parent_id, references(:budget_categories, type: :binary_id, on_delete: :nilify_all)
    end

    create index(:budget_categories, [:parent_id])
  end
end
