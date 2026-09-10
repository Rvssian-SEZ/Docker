defmodule Vdlarr.Downloading.MediaRetentionWorker do
  @moduledoc false

  use Oban.Worker,
    queue: :local_data,
    unique: [period: :infinity, states: [:available, :scheduled, :retryable, :executing]],
    tags: ["media_item", "local_data"]

  use Vdlarr.Media.MediaQuery

  require Logger

  alias Vdlarr.Repo
  alias Vdlarr.Media

  @doc """
  Deletes media items that are past their retention date and prevents
  them from being re-downloaded.

  This worker is scheduled to run daily via the Oban Cron plugin.

  Culling is driven exclusively by a source's `retention_period_days` - a
  source's `download_cutoff_date` only gates what counts as pending for
  future downloads (see `MediaQuery.pending/0`) and never deletes media
  that's already been downloaded, no matter how old it is.

  Returns :ok
  """
  @impl Oban.Worker
  def perform(%Oban.Job{}) do
    cull_cullable_media_items()

    :ok
  end

  defp cull_cullable_media_items do
    cullable_media =
      MediaQuery.new()
      |> MediaQuery.require_assoc(:source)
      |> where(^MediaQuery.cullable())
      |> Repo.all()

    Logger.info("Culling #{length(cullable_media)} media items past their retention date")

    Enum.each(cullable_media, fn media_item ->
      # Setting `prevent_download` does what it says on the tin, but `culled_at` is purely informational.
      # We don't actually do anything with that in terms of queries and it gets set to nil if the media item
      # gets re-downloaded.
      Media.delete_media_files(media_item, %{
        prevent_download: true,
        culled_at: DateTime.utc_now()
      })
    end)
  end

end
