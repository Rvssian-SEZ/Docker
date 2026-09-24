defmodule Coffer.Vendors do
  @moduledoc "Vendors (spec §4.5)."

  import Ecto.Query, warn: false
  alias Coffer.Repo
  alias Coffer.AuditLog
  alias Coffer.Accounts.User
  alias Coffer.Vendors.Vendor

  def list_vendors, do: Repo.all(from v in Vendor, order_by: v.name)
  def get_vendor!(id), do: Repo.get!(Vendor, id)
  def change_vendor(%Vendor{} = vendor, attrs \\ %{}), do: Vendor.changeset(vendor, attrs)

  def create_vendor(attrs, %User{} = actor) do
    changeset = Vendor.changeset(%Vendor{}, attrs)

    Ecto.Multi.new()
    |> Ecto.Multi.insert(:vendor, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{vendor: v} ->
      AuditLog.record(actor.id, :create, "Vendor", v.id, %{after: serialize(v)})
    end)
    |> Repo.transaction()
    |> unwrap()
  end

  def update_vendor(%Vendor{} = vendor, attrs, %User{} = actor) do
    before = serialize(vendor)
    changeset = Vendor.changeset(vendor, attrs)

    Ecto.Multi.new()
    |> Ecto.Multi.update(:vendor, changeset)
    |> Ecto.Multi.run(:audit, fn _repo, %{vendor: v} ->
      AuditLog.record(actor.id, :update, "Vendor", v.id, %{before: before, after: serialize(v)})
    end)
    |> Repo.transaction()
    |> unwrap()
  end

  def delete_vendor(%Vendor{} = vendor, %User{} = actor) do
    before = serialize(vendor)

    Ecto.Multi.new()
    |> Ecto.Multi.delete(:vendor, vendor)
    |> Ecto.Multi.run(:audit, fn _repo, %{vendor: v} ->
      AuditLog.record(actor.id, :delete, "Vendor", v.id, %{before: before})
    end)
    |> Repo.transaction()
    |> unwrap()
  end

  defp serialize(%Vendor{} = v) do
    %{id: v.id, name: v.name, contact_info: v.contact_info, notes: v.notes}
  end

  defp unwrap({:ok, %{vendor: result}}), do: {:ok, result}
  defp unwrap({:error, :vendor, changeset, _changes}), do: {:error, changeset}
end
