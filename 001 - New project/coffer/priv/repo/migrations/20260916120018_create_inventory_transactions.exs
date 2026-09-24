defmodule Coffer.Repo.Migrations.CreateInventoryTransactions do
  use Ecto.Migration

  def change do
    create table(:inventory_transactions, primary_key: false) do
      add :id, :binary_id, primary_key: true

      add :inventory_item_id,
          references(:inventory_items, type: :binary_id, on_delete: :restrict), null: false

      add :transaction_type, :string, null: false
      add :quantity, :integer, null: false
      add :issued_to, :string
      add :date, :date, null: false
      add :created_by_id, references(:users, type: :binary_id, on_delete: :nilify_all)
      add :notes, :text

      timestamps(type: :utc_datetime)
    end

    create index(:inventory_transactions, [:inventory_item_id])

    create constraint(:inventory_transactions, :transaction_type_must_be_valid,
             check: "transaction_type IN ('issue', 'receive', 'adjustment')"
           )

    create constraint(:inventory_transactions, :quantity_must_be_positive, check: "quantity > 0")
  end
end
