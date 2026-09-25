defmodule VdlarrWeb.Sources.SourceLive.IndexGridLiveTest do
  use VdlarrWeb.ConnCase

  import Ecto.Query, warn: false
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

      assert render_element(view, "[data-testid='source-grid-item']:first-child") =~ ~s(src="/sources/#{source.id}/poster?size=thumb")
    end

    test "shows the poster image for a source with only a custom (manually-uploaded) poster", %{conn: conn} do
      source = source_fixture(custom_poster_filepath: thumbnail_filepath_fixture())

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      assert render_element(view, "[data-testid='source-grid-item']:first-child") =~ ~s(src="/sources/#{source.id}/poster?size=thumb")
      refute render_element(view, "[data-testid='source-grid-item']:first-child") =~ "hero-photo"
    end

    test "shows a media item's own thumbnail for a source with no channel/playlist art (eg: :video sources)", %{
      conn: conn
    } do
      source = source_fixture()
      media_item_with_metadata_attachments(%{source_id: source.id})

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      assert render_element(view, "[data-testid='source-grid-item']:first-child") =~ ~s(src="/sources/#{source.id}/poster?size=thumb")
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

    test "refreshes the card's status badge and the summary straight away", %{conn: conn} do
      source_fixture(enabled: true)
      {:ok, view, html} = live_isolated(conn, IndexGridLive, session: create_session())
      assert html =~ "Monitored"
      assert render_element(view, "[data-testid='sources-summary']") =~ "1 monitored"

      view
      |> element(".enabled_toggle_form")
      |> render_change(%{source: %{"enabled" => false}})

      assert render_element(view, "[data-testid='source-grid-item']") =~ "Paused"
      assert render_element(view, "[data-testid='sources-summary']") =~ "0 monitored"
    end
  end

  # NOTE: media_item_fixture/1 eagerly builds its default `source_id` (an extra source) even
  # when one is passed in, so these tests target their own named cards rather than
  # first/last-child, and count expected totals from the DB.
  describe "summary line" do
    test "totals channels, monitored channels and library size", %{conn: conn} do
      source = source_fixture(enabled: true)
      source_fixture(enabled: false)
      media_item_fixture(source_id: source.id, media_size_bytes: 1_073_741_824)

      total = Repo.aggregate(Source, :count)
      monitored = Repo.aggregate(from(s in Source, where: s.enabled), :count)

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      assert render_element(view, "[data-testid='sources-summary']") =~
               "#{total} channels · #{monitored} monitored · 1.0 GB"
    end

    test "counts only hidden sources on the hidden page", %{conn: conn} do
      source_fixture(hidden: false)
      source_fixture(hidden: true)

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: Map.put(create_session(), "show_hidden", true))

      assert render_element(view, "[data-testid='sources-summary']") =~ "1 hidden channel ·"
    end
  end

  describe "download counts" do
    test "shows downloaded out of all indexed videos, and skipped ones in the bar", %{conn: conn} do
      source = source_fixture(custom_name: "Mostly skipped")
      media_item_fixture(source_id: source.id)
      for _ <- 1..3, do: media_item_fixture(source_id: source.id, media_filepath: nil, prevent_download: true)

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())
      card = view |> element("[data-testid='source-grid-item']", "Mostly skipped") |> render()

      assert card =~ "1 of 4 downloaded"
      assert card =~ "width: 25.0%"
      assert card =~ "3 skipped"
    end

    test "only shows a pending badge when something is waiting", %{conn: conn} do
      waiting = source_fixture(custom_name: "Has pending")
      media_item_fixture(source_id: waiting.id, media_filepath: nil)
      done = source_fixture(custom_name: "Nothing pending")
      media_item_fixture(source_id: done.id)

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      assert view |> element("[data-testid='source-grid-item']", "Has pending") |> render() =~ "1 pending"
      refute view |> element("[data-testid='source-grid-item']", "Nothing pending") |> render() =~ "pending-badge"
    end
  end

  describe "every sort key" do
    for key <- ~w(custom_name total_count downloaded_count pending_count media_size_bytes media_profile_name enabled) do
      test "sorting by #{key} works", %{conn: conn} do
        source = source_fixture(custom_name: "Sortable source")
        media_item_fixture(source_id: source.id)

        {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

        assert change_sort_key(view, unquote(key)) =~ "Sortable source"
      end
    end

    test "sorting by downloaded orders by download count, and the toggle reverses it", %{conn: conn} do
      few = source_fixture(custom_name: "Few downloads")
      media_item_fixture(source_id: few.id)
      many = source_fixture(custom_name: "Many downloads")
      for _ <- 1..3, do: media_item_fixture(source_id: many.id)

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())

      first_order = order_of(change_sort_key(view, "downloaded_count"), ["Few downloads", "Many downloads"])
      second_order = order_of(toggle_sort_direction(view), ["Few downloads", "Many downloads"])

      assert Enum.sort([first_order, second_order]) == Enum.sort([["Few downloads", "Many downloads"], ["Many downloads", "Few downloads"]])
    end
  end

  describe "table view columns" do
    test "shows profile, downloaded/total, size, next index and the enable toggle", %{conn: conn} do
      profile = media_profile_fixture(name: "My Profile")
      source = source_fixture(custom_name: "Table source", media_profile_id: profile.id, index_frequency_minutes: -1)
      media_item_fixture(source_id: source.id, media_size_bytes: 2048)

      {:ok, view, _html} = live_isolated(conn, IndexGridLive, session: create_session())
      click_element(view, "button", "Table")
      row = view |> element("[data-testid='source-table-row']", "Table source") |> render()

      assert row =~ "My Profile"
      assert row =~ "/ 1"
      assert row =~ "2.0 KB"
      assert row =~ "Once only"
      assert row =~ "enabled_toggle_form"
    end
  end

  defp order_of(html, names) do
    Enum.sort_by(names, fn name -> :binary.match(html, name) |> elem(0) end)
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
