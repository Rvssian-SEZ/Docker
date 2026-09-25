defmodule VdlarrWeb.PageControllerTest do
  use VdlarrWeb.ConnCase

  import Vdlarr.MediaFixtures
  import Vdlarr.SourcesFixtures

  alias Vdlarr.Downloading.MediaDownloadWorker

  describe "force_download_failed" do
    test "enqueues failed download tasks across every source", %{conn: conn} do
      source_1 = source_fixture()
      source_2 = source_fixture()
      media_item_1 = media_item_fixture(%{source_id: source_1.id, media_filepath: nil, last_error: "Some error"})
      media_item_2 = media_item_fixture(%{source_id: source_2.id, media_filepath: nil, last_error: "Some error"})

      assert [] = all_enqueued(worker: MediaDownloadWorker)
      post(conn, ~p"/force_download_failed")

      assert_enqueued(worker: MediaDownloadWorker, args: %{"id" => media_item_1.id, "force" => true})
      assert_enqueued(worker: MediaDownloadWorker, args: %{"id" => media_item_2.id, "force" => true})
    end

    test "redirects back to Wanted", %{conn: conn} do
      conn = post(conn, ~p"/force_download_failed")
      assert redirected_to(conn) == ~p"/wanted"
    end
  end

  describe "GET /" do
    test "displays the dashboard", %{conn: conn} do
      conn = get(conn, ~p"/")
      html = html_response(conn, 200)

      assert html =~ "Dashboard"
      assert html =~ "Recently Downloaded"
    end
  end

  describe "GET /stats" do
    test "always displays the stats page - there's no onboarding flow", %{conn: conn} do
      conn = get(conn, ~p"/stats")
      html = html_response(conn, 200)

      assert html =~ "History"
      assert html =~ "downloaded"
    end
  end

  describe "GET /activity" do
    test "displays the activity page", %{conn: conn} do
      conn = get(conn, ~p"/activity")
      assert html_response(conn, 200) =~ "Activity"
    end
  end

  describe "GET /wanted" do
    test "displays the wanted page with Pending and Failed tabs", %{conn: conn} do
      html = conn |> get(~p"/wanted") |> html_response(200)

      assert html =~ "Wanted"
      assert html =~ "Pending"
      assert html =~ "Failed (0)"
      refute html =~ "Retry all failed"
    end

    test "offers to retry all failed downloads when there are some", %{conn: conn} do
      source = source_fixture()
      media_item_fixture(%{source_id: source.id, media_filepath: nil, last_error: "Some error"})

      html = conn |> get(~p"/wanted") |> html_response(200)

      assert html =~ "Failed (1)"
      assert html =~ "Retry all failed (1)"
    end
  end

  describe "page titles" do
    test "each section gets its own browser tab title", %{conn: conn} do
      for {path, title} <- [{"/", "Dashboard"}, {"/sources", "Channels"}, {"/wanted", "Wanted"}, {"/stats", "History"}, {"/logs", "Logs"}] do
        assert conn |> get(path) |> html_response(200) =~ "#{title} · VDLarr"
      end
    end

    test "a source's page is titled after the source", %{conn: conn} do
      source = source_fixture(custom_name: "Titled Source")

      assert conn |> get(~p"/sources/#{source.id}") |> html_response(200) =~ "Titled Source · VDLarr"
      assert conn |> get(~p"/sources/#{source.id}/edit") |> html_response(200) =~ "Edit Titled Source · VDLarr"
    end
  end
end
