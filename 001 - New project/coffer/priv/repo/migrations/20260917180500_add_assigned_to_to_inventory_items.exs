defmodule Coffer.Repo.Migrations.AddAssignedToToInventoryItems do
  use Ecto.Migration

  def change do
    alter table(:inventory_items) do
      add :assigned_to, :string
    end
  end
end
