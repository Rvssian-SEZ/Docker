defmodule Pinchflat.Lifecycle.Notifications.JellyfinNotificationWorker do
  @moduledoc """
  Notifies Jellyfin about a newly downloaded media item, in its own job so a slow or
  unreachable Jellyfin server can never block or fail the actual download job. No-ops
  if Jellyfin isn't configured - see JellyfinNotifier.
  """

  use Oban.Worker,
    queue: :local_data,
    tags: ["local_data"]

  require Logger

  alias __MODULE__
  alias Pinchflat.Media
  alias Pinchflat.Lifecycle.Notifications.JellyfinNotifier

  @doc """
  Starts the Jellyfin notification worker for the given media item. Does not attach
  it to a task, matching the pattern used by other fire-and-forget housekeeping
  workers like `Pinchflat.YtDlp.UpdateWorker`.

  Returns {:ok, %Oban.Job{}} | {:error, %Ecto.Changeset{}}
  """
  def kickoff(media_item) do
    Oban.insert(JellyfinNotificationWorker.new(%{media_item_id: media_item.id}))
  end

  @impl Oban.Worker
  def perform(%Oban.Job{args: %{"media_item_id" => media_item_id}}) do
    media_item_id
    |> Media.get_media_item!()
    |> JellyfinNotifier.notify_new_media()
  rescue
    Ecto.NoResultsError -> Logger.info("#{__MODULE__} discarded: media item #{media_item_id} not found")
  end
end
