defmodule Coffer.Repo.Migrations.CreateUsers do
  use Ecto.Migration

  def change do
    create table(:users, primary_key: false) do
      add :id, :binary_id, primary_key: true
      add :authentik_sub, :string, null: false
      add :email, :string, null: false
      add :name, :string, null: false
      add :role, :string
      add :last_login_at, :utc_datetime
      add :active, :boolean, null: false, default: true

      timestamps(type: :utc_datetime)
    end

    create unique_index(:users, [:authentik_sub])

    create constraint(:users, :role_must_be_valid,
             check: "role IS NULL OR role IN ('admin', 'staff', 'read_only')"
           )
  end
end
