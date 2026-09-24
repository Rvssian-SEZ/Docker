defmodule Coffer.Repo.Migrations.CreateBudgetEnvelopes do
  use Ecto.Migration

  def change do
    create table(:budget_envelopes, primary_key: false) do
      add :id, :binary_id, primary_key: true
      add :name, :string, null: false
      add :description, :text
      add :fiscal_year, :integer, null: false
      add :allocated_amount, :decimal, null: false

      add :category_id, references(:budget_categories, type: :binary_id, on_delete: :restrict),
        null: false

      add :created_by_id, references(:users, type: :binary_id, on_delete: :nilify_all)
      add :active, :boolean, null: false, default: true

      timestamps(type: :utc_datetime)
    end

    create index(:budget_envelopes, [:fiscal_year])
    create index(:budget_envelopes, [:category_id])

    create constraint(:budget_envelopes, :allocated_amount_must_be_non_negative,
             check: "allocated_amount >= 0"
           )
  end
end
