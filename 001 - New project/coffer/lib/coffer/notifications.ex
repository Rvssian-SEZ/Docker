defmodule Coffer.Notifications do
  @moduledoc """
  In-app notifications (spec §7). Minimal data layer pulled forward from
  Phase 6 because `ContractRenewalWorker` (Phase 4) needs somewhere to fire
  into — the real-time bell/dropdown UI is still Phase 6's job, this only
  needs to store and broadcast correctly.

  Flagged v1 decision: spec says `user_id: nil` means "broadcast to all
  Admins", but for `:contract_renewal` specifically that would hide renewal
  reminders from Staff, who can fully manage contracts (spec §3.2). Broadcast
  notifications are shown to both Staff and Admin here — narrow this back to
  Admin-only if that turns out to be wrong.
  """

  import Ecto.Query, warn: false
  alias Coffer.Repo
  alias Coffer.Accounts.User
  alias Coffer.Notifications.Notification

  @doc """
  Creates a notification and broadcasts it over PubSub so a future
  real-time bell can subscribe without any change here. `user_id: nil`
  broadcasts to the shared `"notifications:broadcast"` topic instead of a
  per-user one.
  """
  def create(attrs) do
    changeset = Notification.changeset(%Notification{}, attrs)

    case Repo.insert(changeset) do
      {:ok, notification} = ok ->
        Phoenix.PubSub.broadcast(
          Coffer.PubSub,
          topic(notification.user_id),
          {:notification, notification}
        )

        ok

      error ->
        error
    end
  end

  @list_limit 100

  def list_for_user(%User{} = user, opts \\ []) do
    query =
      Notification
      |> where([n], n.user_id == ^user.id or is_nil(n.user_id))
      |> order_by(desc: :inserted_at)
      |> limit(^@list_limit)

    query =
      if Keyword.get(opts, :unread_only, false) do
        where(query, [n], is_nil(n.read_at))
      else
        query
      end

    Repo.all(query)
  end

  def list_recent(%User{} = user, limit \\ 5) do
    Notification
    |> where([n], n.user_id == ^user.id or is_nil(n.user_id))
    |> order_by(desc: :inserted_at)
    |> limit(^limit)
    |> Repo.all()
  end

  def unread_count(%User{} = user) do
    Notification
    |> where([n], n.user_id == ^user.id or is_nil(n.user_id))
    |> where([n], is_nil(n.read_at))
    |> select([n], count(n.id))
    |> Repo.one()
  end

  def get!(id), do: Repo.get!(Notification, id)

  def mark_read(%Notification{} = notification) do
    notification
    |> Notification.changeset(%{read_at: DateTime.utc_now() |> DateTime.truncate(:second)})
    |> Repo.update()
  end

  def mark_all_read(%User{} = user) do
    now = DateTime.utc_now() |> DateTime.truncate(:second)

    Notification
    |> where([n], n.user_id == ^user.id or is_nil(n.user_id))
    |> where([n], is_nil(n.read_at))
    |> Repo.update_all(set: [read_at: now])
  end

  defp topic(nil), do: "notifications:broadcast"
  defp topic(user_id), do: "notifications:#{user_id}"
end
