defmodule VdlarrWeb.Settings.YtDlpVersionLiveTest do
  use VdlarrWeb.ConnCase

  import Phoenix.LiveViewTest

  alias Vdlarr.Settings.YtDlpVersionLive

  describe "initial rendering" do
    test "renders the policy select with the initial value", %{conn: conn} do
      {:ok, _view, html} = live_isolated(conn, YtDlpVersionLive, session: create_session("nightly", nil))

      assert html =~ ~s(name="setting[yt_dlp_update_policy]")
      assert html =~ "Nightly, auto-updated"
    end

    test "does not show the pinned version field for a non-pinned policy", %{conn: conn} do
      {:ok, _view, html} = live_isolated(conn, YtDlpVersionLive, session: create_session("stable", nil))

      refute html =~ ~s(name="setting[yt_dlp_pinned_version]")
    end

    test "shows the pinned version field when the policy is pinned", %{conn: conn} do
      {:ok, _view, html} = live_isolated(conn, YtDlpVersionLive, session: create_session("pinned", "2025.12.08"))

      assert html =~ ~s(name="setting[yt_dlp_pinned_version]")
      assert html =~ ~s(value="2025.12.08")
    end
  end

  describe "switching the policy" do
    test "reveals the pinned version field after selecting pinned", %{conn: conn} do
      {:ok, view, html} = live_isolated(conn, YtDlpVersionLive, session: create_session("stable", nil))
      refute html =~ ~s(name="setting[yt_dlp_pinned_version]")

      html =
        view
        |> element("select")
        |> render_change(%{"setting" => %{"yt_dlp_update_policy" => "pinned"}})

      assert html =~ ~s(name="setting[yt_dlp_pinned_version]")
    end
  end

  describe "checking version availability" do
    test "shows a checkmark when the pinned version is available", %{conn: conn} do
      expect(HTTPClientMock, :get, fn _url, _headers -> {:ok, "{}"} end)

      {:ok, view, _html} = live_isolated(conn, YtDlpVersionLive, session: create_session("pinned", "2025.12.08"))

      html =
        view
        |> element("button")
        |> render_click()

      assert html =~ "hero-check"
    end

    test "shows an x-mark when the pinned version is not available", %{conn: conn} do
      expect(HTTPClientMock, :get, fn _url, _headers -> {:error, "not found"} end)

      {:ok, view, _html} = live_isolated(conn, YtDlpVersionLive, session: create_session("pinned", "2025.12.08"))

      html =
        view
        |> element("button")
        |> render_click()

      assert html =~ "hero-x-mark"
    end

    test "does nothing when the pinned version is blank", %{conn: conn} do
      {:ok, _view, html} = live_isolated(conn, YtDlpVersionLive, session: create_session("pinned", nil))

      # Phoenix.LiveViewTest refuses to click a disabled element (mirroring a real
      # browser), so this asserts the button is rendered disabled rather than
      # clicking it and expecting a no-op.
      assert html =~ "hero-beaker"
      assert html =~ ~r/<button[^>]*disabled[^>]*>/
    end
  end

  defp create_session(policy, pinned_version) do
    %{"policy" => policy, "pinned_version" => pinned_version}
  end
end
