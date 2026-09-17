defmodule Coffer.Repo.Migrations.CreateAuditLogs do
  use Ecto.Migration

  def change do
    create table(:audit_logs, primary_key: false) do
      add :id, :binary_id, primary_key: true
      add :user_id, references(:users, type: :binary_id, on_delete: :nilify_all)
      add :action, :string, null: false
      add :resource_type, :string, null: false
      add :resource_id, :string, null: false
      add :before, :map
      add :after, :map

      timestamps(updated_at: false, type: :utc_datetime)
    end

    create index(:audit_logs, [:resource_type, :resource_id])
    create index(:audit_logs, [:user_id])

    create constraint(:audit_logs, :action_must_be_valid,
             check: "action IN ('create', 'update', 'delete')"
           )
  end
end
