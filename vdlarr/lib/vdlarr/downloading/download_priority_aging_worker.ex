defmodule Vdlarr.Downloading.DownloadPriorityAgingWorker do
  @moduledoc """
  Hourly: bumps every download that has been waiting more than #{6} hours up one priority step
  (towards 0), so long videos queued behind a steady stream of shorter ones still get their
  turn - worst case a 6-priority download reaches the front ~12 hours after it was queued. See
  `MediaDownloadWorker.default_priority/2`.
  """

  use Oban.Worker, queue: :local_data, unique: [period: 600]

  import Ecto.Query

  alias Vdlarr.Repo

  @download_worker "Vdlarr.Downloading.MediaDownloadWorker"
  @wait_before_aging_hours 6

  @impl Oban.Worker
  def perform(%Oban.Job{}) do
    cutoff = DateTime.add(DateTime.utc_now(), -@wait_before_aging_hours * 3600, :second)

    {count, _} =
      from(j in Oban.Job,
        where: j.worker == @download_worker and j.state == "available",
        where: j.priority > 0 and j.inserted_at < ^cutoff
      )
      |> Repo.update_all(inc: [priority: -1])

    {:ok, count}
  end
end
