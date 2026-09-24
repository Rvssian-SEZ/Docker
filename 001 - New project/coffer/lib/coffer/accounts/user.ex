defmodule Coffer.Accounts.User do
  use Coffer.Schema
  import Ecto.Changeset

  @roles [:admin, :staff, :read_only]

  schema "users" do
    field :authentik_sub, :string
    field :email, :string
    field :name, :string
    field :role, Ecto.Enum, values: @roles
    field :last_login_at, :utc_datetime
    field :active, :boolean, default: true

    timestamps(type: :utc_datetime)
  end

  def roles, do: @roles

  def changeset(user, attrs) do
    user
    |> cast(attrs, [:authentik_sub, :email, :name, :role, :last_login_at, :active])
    |> validate_required([:authentik_sub, :email, :name])
    |> unique_constraint(:authentik_sub)
  end
end
