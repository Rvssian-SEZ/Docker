defmodule Coffer.Repo.Migrations.CreateRoleMappings do
  use Ecto.Migration

  def change do
    create table(:role_mappings, primary_key: false) do
      add :id, :binary_id, primary_key: true
      add :authentik_group, :string, null: false
      add :app_role, :string, null: false

      timestamps(type: :utc_datetime)
    end

    create unique_index(:role_mappings, [:authentik_group])

    create constraint(:role_mappings, :app_role_must_be_valid,
             check: "app_role IN ('admin', 'staff', 'read_only')"
           )
  end
end
