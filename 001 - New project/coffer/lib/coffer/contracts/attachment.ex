defmodule Coffer.Contracts.Attachment do
  use Coffer.Schema
  import Ecto.Changeset

  schema "contract_attachments" do
    field :file_path, :string
    field :original_filename, :string
    field :content_type, :string

    belongs_to :contract, Coffer.Contracts.Contract
    belongs_to :uploaded_by, Coffer.Accounts.User

    timestamps(updated_at: false, type: :utc_datetime)
  end

  def changeset(attachment, attrs) do
    attachment
    |> cast(attrs, [:contract_id, :file_path, :original_filename, :content_type, :uploaded_by_id])
    |> validate_required([:contract_id, :file_path, :original_filename])
    |> foreign_key_constraint(:contract_id)
  end
end
