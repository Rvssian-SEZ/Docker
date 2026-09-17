defmodule Coffer.AuditLog do
  @moduledoc """
  Append-only audit trail. Every mutation in every other context calls
  `record/5` (directly, or folded into an `Ecto.Multi`) alongside its write.
  """

  import Ecto.Query, warn: false
  alias Coffer.Repo
  alias Coffer.AuditLog.Entry

  @doc """
  Records one audit entry. `user_id` may be nil only for actions with no
  authenticated actor (none exist yet in this phase; every write path so far
  requires a logged-in Staff/Admin).
  """
  def record(user_id, action, resource_type, resource_id, %{} = changes)
      when action in [:create, :update, :delete] do
    %Entry{}
    |> Entry.changeset(%{
      user_id: user_id,
      action: action,
      resource_type: resource_type,
      resource_id: to_string(resource_id),
      before: Map.get(changes, :before),
      after: Map.get(changes, :after)
    })
    |> Repo.insert()
  end

  @doc "Appends an audit-log insert to an `Ecto.Multi` under `multi_key`."
  def multi_record(multi, multi_key, user_id, action, resource_type, resource_id, changes) do
    Ecto.Multi.run(multi, multi_key, fn _repo, _changes_so_far ->
      record(user_id, action, resource_type, resource_id, changes)
    end)
  end

  @doc """
  Lists entries, newest first, optionally narrowed by `filters` (a map with
  any of `:resource_type`, `:action`, `:user_id` — nil or "" means "all",
  so the values coming straight off a filter form's params can be passed
  through unchanged).
  """
  def list_entries(filters \\ %{}) do
    Entry
    |> filter_by(:resource_type, filters[:resource_type])
    |> filter_by(:action, filters[:action])
    |> filter_by(:user_id, filters[:user_id])
    |> order_by(desc: :inserted_at)
    |> Repo.all()
    |> Repo.preload(:user)
  end

  defp filter_by(query, _field, value) when value in [nil, ""], do: query
  defp filter_by(query, :resource_type, value), do: where(query, [e], e.resource_type == ^value)

  defp filter_by(query, :action, value),
    do: where(query, [e], e.action == ^String.to_existing_atom(value))

  defp filter_by(query, :user_id, value), do: where(query, [e], e.user_id == ^value)

  @doc "Distinct resource types present in the log, for a filter dropdown."
  def distinct_resource_types do
    Entry
    |> distinct(true)
    |> select([e], e.resource_type)
    |> order_by([e], e.resource_type)
    |> Repo.all()
  end
end
