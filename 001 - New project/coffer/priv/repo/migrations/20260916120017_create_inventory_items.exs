defmodule Coffer.Repo.Migrations.CreateInventoryItems do
  use Ecto.Migration

  def change do
    create table(:inventory_items, primary_key: false) do
      add :id, :binary_id, primary_key: true
      add :name, :string, null: false
      add :description, :text
      add :tracking_type, :string, null: false
      add :category, :string
      add :quantity_on_hand, :integer, null: false, default: 0
      add :reorder_threshold, :integer
      add :unit_cost, :decimal
      add :location, :string
      add :created_by_id, references(:users, type: :binary_id, on_delete: :nilify_all)
      add :active, :boolean, null: false, default: true

      timestamps(type: :utc_datetime)
    end

    create index(:inventory_items, [:tracking_type])

    create constraint(:inventory_items, :tracking_type_must_be_valid,
             check: "tracking_type IN ('consumable', 'checkoutable')"
           )

    create constraint(:inventory_items, :quantity_on_hand_not_negative,
             check: "quantity_on_hand >= 0"
           )
  end
end
