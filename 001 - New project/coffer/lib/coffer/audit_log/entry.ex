defmodule Coffer.AuditLog.Entry do
  use Coffer.Schema
  import Ecto.Changeset

  schema "audit_logs" do
    field :action, Ecto.Enum, values: [:create, :update, :delete]
    field :resource_type, :string
    field :resource_id, :string
    field :before, :map
    field :after, :map

    belongs_to :user, Coffer.Accounts.User

    timestamps(updated_at: false, type: :utc_datetime)
  end

  def changeset(entry, attrs) do
    entry
    |> cast(attrs, [:user_id, :action, :resource_type, :resource_id, :before, :after])
    |> validate_required([:action, :resource_type, :resource_id])
    |> foreign_key_constraint(:user_id)
  end
end
