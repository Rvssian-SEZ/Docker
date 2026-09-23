defmodule VdlarrWeb.Pages.DashboardLiveTest do
  use VdlarrWeb.ConnCase

  import Ecto.Query, warn: false
  import Phoenix.LiveViewTest
  import Vdlarr.MediaFixtures
  import Vdlarr.SourcesFixtures

  alias Vdlarr.Pages.DashboardLive
  alias Vdlarr.Downloading.DownloadProgress
  alias Vdlarr.Downloading.MediaDownloadWorker

  describe "empty state" do
    test "renders the dashboard with empty panels", %{conn: conn} do
      {:ok, _view, html} = live_isolated(conn, DashboardLive, session: %{})

      assert html =~ "Dashboard"
      assert html =~ "Nothing downloaded yet."
      assert html =~ "Nothing downloading right now."
      assert html =~ "No recent activity."
    end
  end

  describe "KPI cards" do
    test "counts channels and how many are monitored", %{conn: conn} do
      source_fixture(enabled: true)
      source_fixture(enabled: false)

      {:ok, _view, html} = live_isolated(conn, DashboardLive, session: %{})

      assert html =~ "1 monitored"
    end

    test "shows downloaded vs total videos", %{conn: conn} do
      source = source_fixture()
      media_item_fixture(source_id: source.id, media_downloaded_at: DateTime.utc_now())
      media_item_fixture(source_id: source.id, media_filepath: nil)

      {:ok, _view, html} = live_isolated(conn, DashboardLive, session: %{})

      assert html =~ "1 downloaded (50%)"
    end
  end

  describe "recently downloaded" do
    test "lists downloaded media with its channel", %{conn: conn} do
      source = source_fixture(custom_name: "Test Channel Name")
      media_item = media_item_fixture(source_id: source.id, media_downloaded_at: DateTime.utc_now())

      {:ok, _view, html} = live_isolated(conn, DashboardLive, session: %{})

      assert html =~ media_item.title
      assert html =~ "Test Channel Name"
      refute html =~ "Nothing downloaded yet."
    end
  end

  describe "recent channels" do
    test "labels a disabled channel as paused", %{conn: conn} do
      source_fixture(custom_name: "Paused Channel", enabled: false)

      {:ok, _view, html} = live_isolated(conn, DashboardLive, session: %{})

      assert html =~ "Paused Channel"
      assert html =~ "Paused"
    end

    test "leaves out hidden channels", %{conn: conn} do
      source_fixture(custom_name: "Secret Channel", hidden: true)

      {:ok, _view, html} = live_isolated(conn, DashboardLive, session: %{})

      refute html =~ "Secret Channel"
    end
  end

  describe "queue" do
    test "shows running and queued downloads", %{conn: conn} do
      running = create_download_job(:executing)
      queued = create_download_job(:available)

      {:ok, _view, html} = live_isolated(conn, DashboardLive, session: %{})

      assert html =~ running.title
      assert html =~ queued.title
      assert html =~ "Downloading"
      assert html =~ "Queued"
    end

    test "updates the progress bar from download progress broadcasts", %{conn: conn} do
      media_item = create_download_job(:executing)
      {:ok, view, _html} = live_isolated(conn, DashboardLive, session: %{})

      DownloadProgress.handle_line(media_item.id, ~s(PROGRESS_JSON:{"downloaded_bytes": 42, "total_bytes": 100}))

      assert render(view) =~ "width: 42%"
    end

    test "shows the current stage of a download that's past the transfer", %{conn: conn} do
      media_item = create_download_job(:executing)
      {:ok, view, _html} = live_isolated(conn, DashboardLive, session: %{})

      DownloadProgress.handle_line(media_item.id, "[download] Destination: /tmp/video.mp4")
      DownloadProgress.handle_line(media_item.id, ~s([Metadata] Adding metadata to "/tmp/video.mp4"))

      assert render(view) =~ "Embedding metadata"
    end

    test "shows an in-flight download's state on first render", %{conn: conn} do
      media_item = create_download_job(:executing)
      DownloadProgress.handle_line(media_item.id, "[info] abc: Downloading 1 format(s): 137+140")
      DownloadProgress.handle_line(media_item.id, "[download] Destination: /tmp/video.f140.m4a")

      {:ok, _view, html} = live_isolated(conn, DashboardLive, session: %{})

      assert html =~ "Audio 2/2"
    end

    test "refreshes when a job changes state", %{conn: conn} do
      {:ok, view, _html} = live_isolated(conn, DashboardLive, session: %{})
      media_item = create_download_job(:executing)

      VdlarrWeb.Endpoint.broadcast("job:state", "change", nil)

      assert render(view) =~ media_item.title
    end
  end

  describe "activity" do
    test "includes downloads and failures", %{conn: conn} do
      source = source_fixture()
      downloaded = media_item_fixture(source_id: source.id, media_downloaded_at: DateTime.utc_now())
      failed = media_item_fixture(source_id: source.id, media_filepath: nil, last_error: "boom")

      {:ok, _view, html} = live_isolated(conn, DashboardLive, session: %{})

      assert html =~ "Downloaded #{downloaded.title}"
      assert html =~ "Failed to download #{failed.title}"
    end
  end

  defp create_download_job(job_state) do
    source = source_fixture()
    media_item = media_item_fixture(source_id: source.id, media_filepath: nil)
    {:ok, task} = MediaDownloadWorker.kickoff_with_task(media_item)

    Oban.Job
    |> where([j], j.id == ^task.job_id)
    |> Repo.update_all(set: [state: to_string(job_state)])

    media_item
  end
end
