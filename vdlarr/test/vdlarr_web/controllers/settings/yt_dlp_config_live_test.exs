defmodule VdlarrWeb.Settings.YtDlpConfigLiveTest do
  use VdlarrWeb.ConnCase, async: false

  import Phoenix.LiveViewTest

  alias Vdlarr.Settings.YtDlpConfigLive
  alias Vdlarr.Settings.YtDlpConfigFile

  setup do
    on_exit(fn -> YtDlpConfigFile.clear() end)

    :ok
  end

  describe "initial rendering" do
    test "renders the current contents", %{conn: conn} do
      YtDlpConfigFile.save("--force-ipv4")

      {:ok, _view, html} = live_isolated(conn, YtDlpConfigLive, session: %{})

      assert html =~ "--force-ipv4"
    end

    test "shows 'empty' when nothing is saved", %{conn: conn} do
      YtDlpConfigFile.clear()

      {:ok, _view, html} = live_isolated(conn, YtDlpConfigLive, session: %{})

      assert html =~ "empty"
    end

    test "shows 'in use' when something is saved", %{conn: conn} do
      YtDlpConfigFile.save("--force-ipv4")

      {:ok, _view, html} = live_isolated(conn, YtDlpConfigLive, session: %{})

      assert html =~ "in use"
    end

    test "does not show a Clear button when empty", %{conn: conn} do
      YtDlpConfigFile.clear()

      {:ok, _view, html} = live_isolated(conn, YtDlpConfigLive, session: %{})

      refute html =~ "Clear"
    end
  end

  describe "saving" do
    test "persists the draft contents to disk", %{conn: conn} do
      {:ok, view, _html} = live_isolated(conn, YtDlpConfigLive, session: %{})

      view
      |> element("textarea")
      |> render_change(%{"contents" => "--retries 20"})

      view
      |> element("button", "Save Config")
      |> render_click()

      assert YtDlpConfigFile.read() == "--retries 20"
    end

    test "shows a saved confirmation", %{conn: conn} do
      {:ok, view, _html} = live_isolated(conn, YtDlpConfigLive, session: %{})

      html =
        view
        |> element("button", "Save Config")
        |> render_click()

      assert html =~ "Config saved"
    end
  end

  describe "clearing" do
    test "empties the file", %{conn: conn} do
      YtDlpConfigFile.save("--force-ipv4")

      {:ok, view, _html} = live_isolated(conn, YtDlpConfigLive, session: %{})

      view
      |> element("button", "Clear")
      |> render_click()

      refute YtDlpConfigFile.present?()
    end
  end
end
