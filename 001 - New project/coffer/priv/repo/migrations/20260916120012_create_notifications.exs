defmodule Coffer.Repo.Migrations.CreateNotifications do
  use Ecto.Migration

  def change do
    create table(:notifications, primary_key: false) do
      add :id, :binary_id, primary_key: true
      add :user_id, references(:users, type: :binary_id, on_delete: :nilify_all)
      add :type, :string, null: false
      add :message, :string, null: false
      add :link, :string
      add :read_at, :utc_datetime

      timestamps(updated_at: false, type: :utc_datetime)
    end

    create index(:notifications, [:user_id])

    create constraint(:notifications, :type_must_be_valid,
             check:
               "type IN ('contract_renewal', 'low_stock', 'checkout_overdue', 'budget_over_threshold')"
           )
  end
end
