defmodule PinchflatWeb.Sources.SourceLive.IndexGridLiveTest do
  use PinchflatWeb.ConnCase

  import Phoenix.LiveViewTest
  import Pinchflat.SourcesFixtures
  import Pinchflat.ProfilesFixtures

  alias Pinchflat.Sources.Source
  alias PinchflatWeb.Sources.SourceLive.IndexGridLive

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
