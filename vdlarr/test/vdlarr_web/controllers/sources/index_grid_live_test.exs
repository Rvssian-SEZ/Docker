defmodule VdlarrWeb.Sources.SourceLive.IndexGridLiveTest do
  use VdlarrWeb.ConnCase

  import Phoenix.LiveViewTest
  import Vdlarr.SourcesFixtures
  import Vdlarr.ProfilesFixtures
  import Vdlarr.MediaFixtures

  alias Vdlarr.Sources.Source
  alias VdlarrWeb.Sources.SourceLive.IndexGridLive

  describe "initial rendering" do
    test "lists all sources", %{conn: conn} do
      source = source_fixture()

      {:ok, _view, html} = live_isolated(conn, IndexGridLive, session: create_session())

      assert html =~ source.custom_name
    end

    test "omits sources that have marked_for_deletion_at set", %{conn: conn} do
      source = source_fixture(marked_for_deletion_at: DateTime.utc_now())

      {:ok, _view, html} = live_isolated(conn, IndexGridLive, session: create_session())

      refute html =~ source.custom_name
    end

    test "omits sources who's media profile has marked_for_deletion_at set", %{conn: conn} do
      media_profile = media_profile_fixture(marked_for_deletion_at: DateTime.utc_now())
      source = source_fixture(media_profile_id: media_profile.id)

      {:ok, _view, html} = live_isolated(conn, IndexGridLive, session: create_session())

      refute html =~ source.custom_name
    end

    test "shows a placeholder for sources with no poster image", %{conn: conn} do
      source = source_fixture()

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      assert render_element(view, "[data-testid='source-grid-item']:first-child") =~ source.custom_name
      assert render_element(view, "[data-testid='source-grid-item']:first-child") =~ "hero-photo"
    end

    test "shows the poster image for sources that have one", %{conn: conn} do
      source = source_with_metadata_attachments()

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      assert render_element(view, "[data-testid='source-grid-item']:first-child") =~ ~s(src="/sources/#{source.id}/poster")
    end

    test "shows the poster image for a source with only a custom (manually-uploaded) poster", %{conn: conn} do
      source = source_fixture(custom_poster_filepath: thumbnail_filepath_fixture())

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      assert render_element(view, "[data-testid='source-grid-item']:first-child") =~ ~s(src="/sources/#{source.id}/poster")
      refute render_element(view, "[data-testid='source-grid-item']:first-child") =~ "hero-photo"
    end

    test "shows a media item's own thumbnail for a source with no channel/playlist art (eg: :video sources)", %{
      conn: conn
    } do
      source = source_fixture()
      media_item_with_metadata_attachments(%{source_id: source.id})

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      assert render_element(view, "[data-testid='source-grid-item']:first-child") =~ ~s(src="/sources/#{source.id}/poster")
      refute render_element(view, "[data-testid='source-grid-item']:first-child") =~ "hero-photo"
    end
  end

  describe "hidden sources filtering" do
    test "the main (show_hidden: false) session omits hidden sources", %{conn: conn} do
      visible = source_fixture(custom_name: "Visible Source", hidden: false)
      hidden = source_fixture(custom_name: "Hidden Source", hidden: true)

      {:ok, _view, html} = live_isolated(conn, IndexGridLive, session: create_session())

      assert html =~ visible.custom_name
      refute html =~ hidden.custom_name
    end

    test "the show_hidden: true session shows only hidden sources", %{conn: conn} do
      visible = source_fixture(custom_name: "Visible Source", hidden: false)
      hidden = source_fixture(custom_name: "Hidden Source", hidden: true)

      session = Map.put(create_session(), "show_hidden", true)
      {:ok, _view, html} = live_isolated(conn, IndexGridLive, session: session)

      assert html =~ hidden.custom_name
      refute html =~ visible.custom_name
    end
  end

  describe "when testing sorting" do
    test "sorts by the custom_name by default", %{conn: conn} do
      source1 = source_fixture(custom_name: "Source_B")
      source2 = source_fixture(custom_name: "Source_A")

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())
      assert render_element(view, "[data-testid='source-grid-item']:first-child") =~ source2.custom_name
      assert render_element(view, "[data-testid='source-grid-item']:last-child") =~ source1.custom_name
    end

    test "changing the sort key sorts by that attribute", %{conn: conn} do
      source1 = source_fixture(custom_name: "Source_A", enabled: true)
      source2 = source_fixture(custom_name: "Source_A", enabled: false)

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      change_sort_key(view, "enabled")

      assert render_element(view, "[data-testid='source-grid-item']:first-child") =~ source2.custom_name
      assert render_element(view, "[data-testid='source-grid-item']:last-child") =~ source1.custom_name
    end

    test "clicking the direction toggle flips the sort direction for the current key", %{conn: conn} do
      source1 = source_fixture(custom_name: "Source_B")
      source2 = source_fixture(custom_name: "Source_A")

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      toggle_sort_direction(view)

      assert render_element(view, "[data-testid='source-grid-item']:first-child") =~ source1.custom_name
      assert render_element(view, "[data-testid='source-grid-item']:last-child") =~ source2.custom_name
    end

    test "name is sorted without case sensitivity", %{conn: conn} do
      source1 = source_fixture(custom_name: "Source_B")
      source2 = source_fixture(custom_name: "source_a")

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      assert render_element(view, "[data-testid='source-grid-item']:first-child") =~ source2.custom_name
      assert render_element(view, "[data-testid='source-grid-item']:last-child") =~ source1.custom_name
    end
  end

  describe "when testing pagination" do
    test "moving to the next page loads new records", %{conn: conn} do
      source1 = source_fixture(custom_name: "Source_A")
      source2 = source_fixture(custom_name: "Source_B")

      session = Map.merge(create_session(), %{"results_per_page" => 1})
      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: session)

      assert render(view) =~ source1.custom_name
      refute render(view) =~ source2.custom_name

      click_element(view, "span.pagination-next")

      refute render(view) =~ source1.custom_name
      assert render(view) =~ source2.custom_name
    end
  end

  describe "when testing the view mode toggle" do
    test "defaults to the poster grid", %{conn: conn} do
      source = source_fixture()

      {:ok, _view, html} = live_isolated(conn, IndexGridLive, session: create_session())

      assert html =~ source.custom_name
      assert html =~ "data-testid=\"source-grid-item\""
    end

    test "switching to table mode renders a table instead of the poster grid", %{conn: conn} do
      source = source_fixture()

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      view
      |> element("button[phx-value-mode='table']")
      |> render_click()

      html = render(view)
      assert html =~ source.custom_name
      assert html =~ "<table"
      refute html =~ "data-testid=\"source-grid-item\""
    end
  end

  describe "when testing search" do
    test "filters sources by name", %{conn: conn} do
      match = source_fixture(custom_name: "Matching Source")
      no_match = source_fixture(custom_name: "Something Else")

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      view
      |> element("#source-search-form")
      |> render_change(%{"search_term" => "Matching"})

      html = render(view)
      assert html =~ match.custom_name
      refute html =~ no_match.custom_name
    end

    test "clearing the search term shows all sources again", %{conn: conn} do
      match = source_fixture(custom_name: "Matching Source")
      no_match = source_fixture(custom_name: "Something Else")

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      view
      |> element("#source-search-form")
      |> render_change(%{"search_term" => "Matching"})

      view
      |> element("#source-search-form")
      |> render_change(%{"search_term" => ""})

      html = render(view)
      assert html =~ match.custom_name
      assert html =~ no_match.custom_name
    end
  end

  describe "when testing the enable toggle" do
    test "updates the source's enabled status", %{conn: conn} do
      source = source_fixture(enabled: true)
      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      view
      |> element(".enabled_toggle_form")
      |> render_change(%{source: %{"enabled" => false}})

      assert %{enabled: false} = Repo.get!(Source, source.id)
    end
  end

  defp click_element(view, selector, text_filter \\ nil) do
    view
    |> element(selector, text_filter)
    |> render_click()
  end

  defp render_element(view, selector) do
    view
    |> element(selector)
    |> render()
  end

  defp change_sort_key(view, sort_key) do
    view
    |> element("#source-sort-form")
    |> render_change(%{"sort_key" => sort_key})
  end

  defp toggle_sort_direction(view) do
    view
    |> element("#sort-direction-toggle")
    |> render_click()
  end

  defp create_session do
    %{
      "initial_sort_key" => :custom_name,
      "initial_sort_direction" => :asc,
      "results_per_page" => 10
    }
  end
end
