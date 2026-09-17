defmodule Coffer.Repo.Migrations.CreateBudgetCategories do
  use Ecto.Migration

  def change do
    create table(:budget_categories, primary_key: false) do
      add :id, :binary_id, primary_key: true
      add :name, :string, null: false

      timestamps(type: :utc_datetime)
    end

    create unique_index(:budget_categories, [:name])
  end
end
