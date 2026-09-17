defmodule Coffer.Notifications.Notification do
  use Coffer.Schema
  import Ecto.Changeset

  @types [:contract_renewal, :low_stock, :checkout_overdue, :budget_over_threshold]

  schema "notifications" do
    field :type, Ecto.Enum, values: @types
    field :message, :string
    field :link, :string
    field :read_at, :utc_datetime

    belongs_to :user, Coffer.Accounts.User

    timestamps(updated_at: false, type: :utc_datetime)
  end

  def types, do: @types

  def changeset(notification, attrs) do
    notification
    |> cast(attrs, [:user_id, :type, :message, :link, :read_at])
    |> validate_required([:type, :message])
    |> foreign_key_constraint(:user_id)
  end
end
