defmodule VdlarrWeb.Pages.JobTableLiveTest do
  use VdlarrWeb.ConnCase

  import Ecto.Query, warn: false
  import Phoenix.LiveViewTest
  import Vdlarr.MediaFixtures
  import Vdlarr.SourcesFixtures

  alias Vdlarr.Pages.JobTableLive
  alias Vdlarr.Downloading.MediaDownloadWorker
  alias Vdlarr.Metadata.SourceMetadataStorageWorker

  describe "initial rendering" do
    test "shows message when no records", %{conn: conn} do
      {:ok, _view, html} = live_isolated(conn, JobTableLive, session: %{})

      assert html =~ "Nothing Here!"
      refute html =~ "Subject"
    end

    test "shows records when present", %{conn: conn} do
      {_source, _media_item, _task, _job} = create_media_item_job()
      {:ok, _view, html} = live_isolated(conn, JobTableLive, session: %{})

      assert html =~ "Subject"
    end

    test "doesn't show records in a terminal state", %{conn: conn} do
      {_source, _media_item, _task, _job} = create_media_item_job(:completed)
      {_source, _media_item, _task, _job} = create_media_item_job(:discarded)
      {_source, _media_item, _task, _job} = create_media_item_job(:cancelled)
      {:ok, _view, html} = live_isolated(conn, JobTableLive, session: %{})

      assert html =~ "Nothing Here!"
      refute html =~ "Subject"
    end

    test "shows records that are queued, scheduled, or retrying - not just the executing one", %{conn: conn} do
      {source1, _task, _job} = create_source_job(:available)
      {source2, _task, _job} = create_source_job(:scheduled)
      {source3, _task, _job} = create_source_job(:retryable)
      {:ok, _view, html} = live_isolated(conn, JobTableLive, session: %{})

      assert html =~ source1.custom_name
      assert html =~ source2.custom_name
      assert html =~ source3.custom_name
    end
  end

  describe "job status column" do
    test "labels each job by its current state", %{conn: conn} do
      create_media_item_job(:executing)
      create_media_item_job(:available)
      create_media_item_job(:scheduled)
      create_media_item_job(:retryable)
      {:ok, _view, html} = live_isolated(conn, JobTableLive, session: %{})

      assert html =~ "Running"
      assert html =~ "Queued"
      assert html =~ "Scheduled"
      assert html =~ "Retrying"
    end

    test "shows the executing job before queued/scheduled ones", %{conn: conn} do
      {queued_source, _task, _job} = create_source_job(:available, custom_name: "Queued Source")
      {running_source, _task, _job} = create_source_job(:executing, custom_name: "Running Source")
      {:ok, _view, html} = live_isolated(conn, JobTableLive, session: %{})

      {running_index, _} = :binary.match(html, running_source.custom_name)
      {queued_index, _} = :binary.match(html, queued_source.custom_name)

      assert running_index < queued_index
    end
  end

  describe "job rendering" do
    test "shows worker name", %{conn: conn} do
      {_source, _media_item, _task, _job} = create_media_item_job()
      {:ok, _view, html} = live_isolated(conn, JobTableLive, session: %{})

      assert html =~ "Downloading Media"
    end

    test "shows the media item title", %{conn: conn} do
      {_source, media_item, _task, _job} = create_media_item_job()
      {:ok, _view, html} = live_isolated(conn, JobTableLive, session: %{})

      assert html =~ media_item.title
    end

    test "shows a media item link", %{conn: conn} do
      {_source, media_item, _task, _job} = create_media_item_job()
      {:ok, _view, html} = live_isolated(conn, JobTableLive, session: %{})

      assert html =~ ~p"/sources/#{media_item.source_id}/media/#{media_item}"
    end

    test "shows the source custom name", %{conn: conn} do
      {source, _task, _job} = create_source_job()
      {:ok, _view, html} = live_isolated(conn, JobTableLive, session: %{})

      assert html =~ source.custom_name
    end

    test "shows a source link", %{conn: conn} do
      {source, _task, _job} = create_source_job()
      {:ok, _view, html} = live_isolated(conn, JobTableLive, session: %{})

      assert html =~ ~p"/sources/#{source.id}"
    end

    test "listens for job:state change events", %{conn: conn} do
      {_source, _media_item, _task, _job} = create_media_item_job()
      {:ok, _view, _html} = live_isolated(conn, JobTableLive, session: %{})

      VdlarrWeb.Endpoint.broadcast("job:state", "change", nil)

      assert_receive %Phoenix.Socket.Broadcast{topic: "job:state", event: "change", payload: nil}
    end
  end

  defp create_media_item_job(job_state \\ :executing) do
    source = source_fixture()
    media_item = media_item_fixture(source_id: source.id)
    {:ok, task} = MediaDownloadWorker.kickoff_with_task(media_item)

    Oban.Job
    |> where([j], j.id == ^task.job_id)
    |> Repo.update_all(set: [state: to_string(job_state)])

    job = Repo.get!(Oban.Job, task.job_id)

    {source, media_item, task, job}
  end

  defp create_source_job(job_state \\ :executing, source_attrs \\ []) do
    source = source_fixture(source_attrs)
    {:ok, task} = SourceMetadataStorageWorker.kickoff_with_task(source)

    Oban.Job
    |> where([j], j.id == ^task.job_id)
    |> Repo.update_all(set: [state: to_string(job_state)])

    job = Repo.get!(Oban.Job, task.job_id)

    {source, task, job}
  end
end
