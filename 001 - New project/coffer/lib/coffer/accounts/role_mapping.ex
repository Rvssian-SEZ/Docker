defmodule Coffer.Accounts.RoleMapping do
  use Coffer.Schema
  import Ecto.Changeset

  schema "role_mappings" do
    field :authentik_group, :string
    field :app_role, Ecto.Enum, values: Coffer.Accounts.User.roles()

    timestamps(type: :utc_datetime)
  end

  def changeset(role_mapping, attrs) do
    role_mapping
    |> cast(attrs, [:authentik_group, :app_role])
    |> validate_required([:authentik_group, :app_role])
    |> unique_constraint(:authentik_group)
  end
end
