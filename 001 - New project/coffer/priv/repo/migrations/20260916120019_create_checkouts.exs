defmodule Coffer.Repo.Migrations.CreateCheckouts do
  use Ecto.Migration

  def change do
    create table(:checkouts, primary_key: false) do
      add :id, :binary_id, primary_key: true

      add :inventory_item_id,
          references(:inventory_items, type: :binary_id, on_delete: :restrict), null: false

      add :checked_out_to, :string, null: false
      add :checked_out_by_id, references(:users, type: :binary_id, on_delete: :nilify_all)
      add :checked_out_at, :utc_datetime, null: false
      add :due_back_at, :utc_datetime
      add :checked_in_at, :utc_datetime
      add :condition_notes_out, :text
      add :condition_notes_in, :text
      add :status, :string, null: false, default: "out"

      timestamps(type: :utc_datetime)
    end

    create index(:checkouts, [:inventory_item_id])
    create index(:checkouts, [:status])
    create index(:checkouts, [:due_back_at])

    create constraint(:checkouts, :status_must_be_valid,
             check: "status IN ('out', 'returned', 'overdue', 'lost')"
           )
  end
end
