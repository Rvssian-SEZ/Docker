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

  def list_entries do
    Entry
    |> order_by(desc: :inserted_at)
    |> Repo.all()
    |> Repo.preload(:user)
  end
end
