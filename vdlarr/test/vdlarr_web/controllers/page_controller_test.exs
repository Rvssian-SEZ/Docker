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

    test "redirects to the app root", %{conn: conn} do
      conn = post(conn, ~p"/force_download_failed")
      assert redirected_to(conn) == ~p"/"
    end
  end

  describe "GET /stats" do
    test "always displays the stats page - there's no onboarding flow", %{conn: conn} do
      conn = get(conn, ~p"/stats")
      assert html_response(conn, 200) =~ "Menu"
    end
  end

  describe "GET /activity" do
    test "displays the activity page", %{conn: conn} do
      conn = get(conn, ~p"/activity")
      assert html_response(conn, 200) =~ "Activity"
    end
  end

  describe "GET /wanted" do
    test "displays the wanted page", %{conn: conn} do
      conn = get(conn, ~p"/wanted")
      assert html_response(conn, 200) =~ "Wanted"
    end
  end
end
