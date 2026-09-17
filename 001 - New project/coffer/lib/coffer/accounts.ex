defmodule Coffer.Accounts do
  @moduledoc """
  Users, role mappings, and translating Authentik OIDC claims into an
  authorized `Coffer.Accounts.User`.
  """

  import Ecto.Query, warn: false
  alias Coffer.Repo
  alias Coffer.AuditLog
  alias Coffer.Accounts.{User, RoleMapping}

  @role_priority [admin: 3, staff: 2, read_only: 1]

  def get_user!(id), do: Repo.get!(User, id)
  def get_user_by_authentik_sub(sub), do: Repo.get_by(User, authentik_sub: sub)
  def list_users, do: Repo.all(from u in User, order_by: u.name)

  @doc """
  Upserts a user from OIDC claims and refreshes their role from the current
  `role_mappings` table on every login (spec §3.1 — role changes in
  Authentik must propagate on next login, not just at first login).

  `groups` with no matching row in `role_mappings` results in `role: nil`
  (no usable role, access denied everywhere) rather than defaulting to
  `:read_only` or `:admin` — flagged v1 decision, confirm with Alex if a
  different default is wanted.
  """
  def upsert_from_oidc(%{"sub" => sub} = claims) do
    groups = Map.get(claims, "groups", [])
    role = resolve_role(groups)

    attrs = %{
      authentik_sub: sub,
      email: Map.get(claims, "email"),
      name: Map.get(claims, "name") || Map.get(claims, "preferred_username") || sub,
      role: role,
      last_login_at: DateTime.utc_now() |> DateTime.truncate(:second),
      active: true
    }

    case get_user_by_authentik_sub(sub) do
      nil -> %User{}
      user -> user
    end
    |> User.changeset(attrs)
    |> Repo.insert_or_update()
  end

  defp resolve_role(groups) when is_list(groups) do
    mapped_roles =
      RoleMapping
      |> where([rm], rm.authentik_group in ^groups)
      |> select([rm], rm.app_role)
      |> Repo.all()

    Enum.max_by(mapped_roles, &Keyword.fetch!(@role_priority, &1), fn -> nil end)
  end

  defp resolve_role(_groups), do: nil

  # -- Role mappings (Admin-only management, per Policy) --

  def list_role_mappings do
    Repo.all(from rm in RoleMapping, order_by: rm.authentik_group)
  end

  def get_role_mapping!(id), do: Repo.get!(RoleMapping, id)

  def create_role_mapping(attrs, %User{} = actor) do
    changeset = RoleMapping.changeset(%RoleMapping{}, attrs)

    Ecto.Multi.new()
    |> Ecto.Multi.insert(:role_mapping, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{role_mapping: rm} ->
      AuditLog.record(actor.id, :create, "RoleMapping", rm.id, %{after: serialize(rm)})
    end)
    |> Repo.transaction()
    |> unwrap(:role_mapping)
  end

  def update_role_mapping(%RoleMapping{} = role_mapping, attrs, %User{} = actor) do
    before = serialize(role_mapping)
    changeset = RoleMapping.changeset(role_mapping, attrs)

    Ecto.Multi.new()
    |> Ecto.Multi.update(:role_mapping, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{role_mapping: rm} ->
      AuditLog.record(actor.id, :update, "RoleMapping", rm.id, %{
        before: before,
        after: serialize(rm)
      })
    end)
    |> Repo.transaction()
    |> unwrap(:role_mapping)
  end

  def delete_role_mapping(%RoleMapping{} = role_mapping, %User{} = actor) do
    before = serialize(role_mapping)

    Ecto.Multi.new()
    |> Ecto.Multi.delete(:role_mapping, role_mapping)
    |> Ecto.Multi.run(:audit, fn _repo, %{role_mapping: rm} ->
      AuditLog.record(actor.id, :delete, "RoleMapping", rm.id, %{before: before})
    end)
    |> Repo.transaction()
    |> unwrap(:role_mapping)
  end

  def change_role_mapping(%RoleMapping{} = role_mapping, attrs \\ %{}) do
    RoleMapping.changeset(role_mapping, attrs)
  end

  defp serialize(%RoleMapping{} = rm) do
    %{id: rm.id, authentik_group: rm.authentik_group, app_role: rm.app_role}
  end

  defp unwrap({:ok, %{role_mapping: result}}, :role_mapping), do: {:ok, result}

  defp unwrap({:error, :role_mapping, changeset, _changes}, :role_mapping),
    do: {:error, changeset}
end
