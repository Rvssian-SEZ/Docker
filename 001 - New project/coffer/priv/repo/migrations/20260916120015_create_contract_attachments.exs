defmodule Coffer.Repo.Migrations.CreateContractAttachments do
  use Ecto.Migration

  def change do
    create table(:contract_attachments, primary_key: false) do
      add :id, :binary_id, primary_key: true

      add :contract_id, references(:contracts, type: :binary_id, on_delete: :delete_all),
        null: false

      add :file_path, :string, null: false
      add :original_filename, :string, null: false
      add :content_type, :string
      add :uploaded_by_id, references(:users, type: :binary_id, on_delete: :nilify_all)

      timestamps(updated_at: false, type: :utc_datetime)
    end

    create index(:contract_attachments, [:contract_id])
  end
end
