defmodule Coffer.Repo.Migrations.CreateVendors do
  use Ecto.Migration

  def change do
    create table(:vendors, primary_key: false) do
      add :id, :binary_id, primary_key: true
      add :name, :string, null: false
      add :contact_info, :map, null: false, default: %{}
      add :notes, :text

      timestamps(type: :utc_datetime)
    end

    create index(:vendors, [:name])
  end
end
