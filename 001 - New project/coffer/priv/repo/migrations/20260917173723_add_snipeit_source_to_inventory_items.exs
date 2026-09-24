defmodule Coffer.Repo.Migrations.AddSnipeitSourceToInventoryItems do
  use Ecto.Migration

  def change do
    alter table(:inventory_items) do
      add :source, :string, null: false, default: "manual"
      add :external_id, :string
      add :external_updated_at, :utc_datetime
    end

    create unique_index(:inventory_items, [:external_id],
             where: "source = 'snipeit'",
             name: :inventory_items_snipeit_external_id_index
           )
  end
end
