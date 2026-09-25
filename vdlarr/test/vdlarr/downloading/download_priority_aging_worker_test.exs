defmodule Vdlarr.Downloading.DownloadPriorityAgingWorkerTest do
  use Vdlarr.DataCase

  import Ecto.Query
  import Vdlarr.MediaFixtures

  alias Vdlarr.Downloading.MediaDownloadWorker
  alias Vdlarr.Downloading.DownloadPriorityAgingWorker

  defp queued_download(priority, hours_ago, state \\ "available") do
    {:ok, task} = MediaDownloadWorker.kickoff_with_task(media_item_fixture(media_filepath: nil), %{}, priority: priority)
    inserted_at = DateTime.add(DateTime.utc_now(), -hours_ago * 3600, :second)

    Repo.update_all(from(j in Oban.Job, where: j.id == ^task.job_id), set: [inserted_at: inserted_at, state: state])

    task.job_id
  end

  defp priority_of(job_id), do: Repo.get!(Oban.Job, job_id).priority

  test "bumps downloads that have waited more than 6 hours up one step" do
    old = queued_download(6, 7)
    fresh = queued_download(6, 1)

    assert {:ok, 1} = perform_job(DownloadPriorityAgingWorker, %{})

    assert priority_of(old) == 5
    assert priority_of(fresh) == 6
  end

  test "never goes below 0 and leaves running or scheduled jobs alone" do
    top = queued_download(0, 10)
    running = queued_download(6, 10, "executing")
    scheduled = queued_download(6, 10, "scheduled")

    perform_job(DownloadPriorityAgingWorker, %{})

    assert priority_of(top) == 0
    assert priority_of(running) == 6
    assert priority_of(scheduled) == 6
  end

  test "doesn't touch other workers' jobs" do
    {:ok, other} = Oban.insert(Vdlarr.Downloading.MediaRetentionWorker.new(%{}, priority: 6))
    Repo.update_all(from(j in Oban.Job, where: j.id == ^other.id), set: [inserted_at: DateTime.add(DateTime.utc_now(), -48 * 3600, :second)])

    perform_job(DownloadPriorityAgingWorker, %{})

    assert Repo.get!(Oban.Job, other.id).priority == 6
  end
end
