defmodule VdlarrWeb.Sources.MediaItemTableLiveTest do
  use VdlarrWeb.ConnCase

  import Phoenix.LiveViewTest
  import Vdlarr.MediaFixtures
  import Vdlarr.SourcesFixtures
  import Vdlarr.ProfilesFixtures

  alias Vdlarr.Media
  alias VdlarrWeb.Sources.MediaItemTableLive

  setup do
    source = source_fixture()

    {:ok, source: source}
  end

  describe "initial rendering" do
    test "shows message when no records", %{conn: conn, source: source} do
      {:ok, _view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source))

      assert html =~ "Nothing Here!"
      refute html =~ "Showing"
    end

    test "shows records when present", %{conn: conn, source: source} do
      media_item = media_item_fixture(source_id: source.id, media_filepath: nil)

      {:ok, _view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source))

      assert html =~ "Showing"
      assert html =~ "Title"
      assert html =~ media_item.title
    end
  end

  describe "media_state" do
    test "shows pending media when pending", %{conn: conn, source: source} do
      downloaded_media_item = media_item_fixture(source_id: source.id)
      pending_media_item = media_item_fixture(source_id: source.id, media_filepath: nil)

      {:ok, _view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "pending"))

      assert html =~ pending_media_item.title
      refute html =~ downloaded_media_item.title
    end

    test "shows downloaded media when downloaded", %{conn: conn, source: source} do
      downloaded_media_item = media_item_fixture(source_id: source.id)
      pending_media_item = media_item_fixture(source_id: source.id, media_filepath: nil)

      {:ok, _view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "downloaded"))

      assert html =~ downloaded_media_item.title
      refute html =~ pending_media_item.title
    end

    test "shows records that aren't pending or downloaded when other", %{conn: conn} do
      media_profile = media_profile_fixture(shorts_behaviour: :exclude)
      source = source_fixture(media_profile_id: media_profile.id)

      downloaded_media_item = media_item_fixture(source_id: source.id)
      pending_media_item = media_item_fixture(source_id: source.id, media_filepath: nil)
      other_media_item = media_item_fixture(source_id: source.id, media_filepath: nil, short_form_content: true)

      {:ok, _view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "other"))

      assert html =~ other_media_item.title
      refute html =~ downloaded_media_item.title
      refute html =~ pending_media_item.title
    end

    test "shows 'Manually Ignored' column when other", %{conn: conn, source: source} do
      _media_item = media_item_fixture(source_id: source.id, prevent_download: true, media_filepath: nil)

      {:ok, _view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "other"))

      assert html =~ "Manually Ignored?"
    end

    test "shows media with an error when failed", %{conn: conn, source: source} do
      failed_media_item = media_item_fixture(source_id: source.id, media_filepath: nil, last_error: "Some error")
      pending_media_item = media_item_fixture(source_id: source.id, media_filepath: nil)

      {:ok, _view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "failed"))

      assert html =~ failed_media_item.title
      refute html =~ pending_media_item.title
    end

    test "does not show a failed item that has already been downloaded", %{conn: conn, source: source} do
      media_item = media_item_fixture(source_id: source.id, last_error: "Some error")

      {:ok, _view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "failed"))

      refute html =~ media_item.title
    end

    test "does not show a manually ignored failed item", %{conn: conn, source: source} do
      media_item =
        media_item_fixture(source_id: source.id, media_filepath: nil, last_error: "Some error", prevent_download: true)

      {:ok, _view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "failed"))

      refute html =~ media_item.title
    end

    test "shows a retry link on the failed tab", %{conn: conn, source: source} do
      media_item = media_item_fixture(source_id: source.id, media_filepath: nil, last_error: "Some error")

      {:ok, _view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "failed"))

      assert html =~ ~p"/sources/#{source.id}/media/#{media_item.id}/force_download"
    end

    test "shows a force download link on the pending tab", %{conn: conn, source: source} do
      media_item = media_item_fixture(source_id: source.id, media_filepath: nil)

      {:ok, _view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "pending"))

      assert html =~ ~p"/sources/#{source.id}/media/#{media_item.id}/force_download"
    end

    test "shows a non-retryable badge for known-unrecoverable errors", %{conn: conn, source: source} do
      _media_item =
        media_item_fixture(source_id: source.id, media_filepath: nil, last_error: "ERROR: Video unavailable")

      {:ok, _view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "failed"))

      assert html =~ "Won&#39;t retry automatically"
    end
  end

  describe "download progress" do
    test "renders progress when a broadcast is received on the pending tab", %{conn: conn, source: source} do
      media_item = media_item_fixture(source_id: source.id, media_filepath: nil)

      {:ok, view, _html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "pending"))

      broadcast_progress(view, media_item.id, 50, 100)

      assert render(view) =~ "50%"
    end

    test "doesn't show a Progress column on the downloaded tab", %{conn: conn, source: source} do
      _media_item = media_item_fixture(source_id: source.id)

      {:ok, _view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "downloaded"))

      refute html =~ "Progress"
    end

    test "doesn't show a Progress column on the other tab", %{conn: conn, source: source} do
      _media_item = media_item_fixture(source_id: source.id, media_filepath: nil, short_form_content: true)

      {:ok, _view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "other"))

      refute html =~ "Progress"
    end

    test "renders progress when a broadcast is received on the failed tab", %{conn: conn, source: source} do
      media_item = media_item_fixture(source_id: source.id, media_filepath: nil, last_error: "Some error")

      {:ok, view, _html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "failed"))

      broadcast_progress(view, media_item.id, 50, 100)

      assert render(view) =~ "50%"
    end

    test "a failed item drops off the failed tab once it successfully downloads", %{conn: conn, source: source} do
      media_item = media_item_fixture(source_id: source.id, media_filepath: nil, last_error: "Some error")

      {:ok, view, html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "failed"))
      assert html =~ media_item.title

      Media.update_media_item(media_item, %{
        media_downloaded_at: DateTime.utc_now(),
        media_filepath: "/some/path.mp4",
        last_error: nil
      })

      VdlarrWeb.Endpoint.broadcast("job:state", "change", nil)
      :sys.get_state(view.pid)

      refute render(view) =~ media_item.title
    end

    test "clears progress for items no longer pending on a job:state change", %{conn: conn, source: source} do
      media_item = media_item_fixture(source_id: source.id, media_filepath: nil)

      {:ok, view, _html} = live_isolated(conn, MediaItemTableLive, session: create_session(source, "pending"))

      broadcast_progress(view, media_item.id, 50, 100)
      assert render(view) =~ "50%"

      Media.update_media_item(media_item, %{media_downloaded_at: DateTime.utc_now(), media_filepath: "/some/path.mp4"})
      VdlarrWeb.Endpoint.broadcast("job:state", "change", nil)
      :sys.get_state(view.pid)

      refute render(view) =~ "50%"
    end
  end

  # `Endpoint.broadcast/3` is async - `:sys.get_state/1` forces a synchronous
  # round-trip with the LiveView process, guaranteeing it's processed the
  # broadcast (and re-rendered) before we assert on its output.
  defp broadcast_progress(view, media_item_id, downloaded_bytes, total_bytes) do
    VdlarrWeb.Endpoint.broadcast("downloads:progress", "progress", %{
      media_item_id: media_item_id,
      progress: %{"status" => "downloading", "downloaded_bytes" => downloaded_bytes, "total_bytes" => total_bytes}
    })

    :sys.get_state(view.pid)
  end

  defp create_session(source, media_state \\ "pending") do
    %{"source_id" => source.id, "media_state" => media_state}
  end
end
