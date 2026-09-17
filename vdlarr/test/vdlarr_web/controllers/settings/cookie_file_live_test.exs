defmodule VdlarrWeb.Settings.CookieFileLiveTest do
  use VdlarrWeb.ConnCase, async: false

  import Phoenix.LiveViewTest

  alias Vdlarr.Settings.CookieFileLive
  alias Vdlarr.Settings.CookieFile

  setup do
    on_exit(fn -> CookieFile.clear() end)

    :ok
  end

  defp upload_cookies(view, contents) do
    entry = file_input(view, "#cookie-file-form", :cookies, [%{name: "cookies.txt", content: contents, type: "text/plain"}])
    render_upload(entry, "cookies.txt")

    view
    |> form("#cookie-file-form")
    |> render_submit()
  end

  describe "initial rendering" do
    test "shows 'Empty' when nothing is saved", %{conn: conn} do
      CookieFile.clear()

      {:ok, _view, html} = live_isolated(conn, CookieFileLive, session: %{})

      assert html =~ "Empty"
    end

    test "shows 'Populated' when something is saved", %{conn: conn} do
      CookieFile.save_from_path(write_temp_cookie_file("some cookie contents"))

      {:ok, _view, html} = live_isolated(conn, CookieFileLive, session: %{})

      assert html =~ "Populated"
    end

    test "does not show a Clear button when empty", %{conn: conn} do
      CookieFile.clear()

      {:ok, _view, html} = live_isolated(conn, CookieFileLive, session: %{})

      refute html =~ "Clear"
    end
  end

  describe "uploading" do
    test "persists the uploaded file's contents to disk", %{conn: conn} do
      {:ok, view, _html} = live_isolated(conn, CookieFileLive, session: %{})

      upload_cookies(view, "some cookie contents")

      assert File.read!(CookieFile.filepath()) == "some cookie contents"
    end

    test "shows Populated after a successful upload", %{conn: conn} do
      {:ok, view, _html} = live_isolated(conn, CookieFileLive, session: %{})

      html = upload_cookies(view, "some cookie contents")

      assert html =~ "Populated"
    end
  end

  describe "clearing" do
    test "empties the file", %{conn: conn} do
      CookieFile.save_from_path(write_temp_cookie_file("some cookie contents"))

      {:ok, view, _html} = live_isolated(conn, CookieFileLive, session: %{})

      view
      |> element("button", "Clear")
      |> render_click()

      refute CookieFile.present?()
    end
  end

  describe "validating" do
    test "shows the result of validating the current file", %{conn: conn} do
      contents = ".example.com\tTRUE\t/\tFALSE\t9999999999\tname\tvalue"
      CookieFile.save_from_path(write_temp_cookie_file(contents))

      {:ok, view, _html} = live_isolated(conn, CookieFileLive, session: %{})

      html =
        view
        |> element("[phx-click='validate_cookies']")
        |> render_click()

      assert html =~ "Valid: 1 cookie(s), 1 active"
    end
  end

  defp write_temp_cookie_file(contents) do
    path = Path.join(System.tmp_dir!(), "cookie_file_live_test_#{System.unique_integer([:positive])}.txt")
    File.write!(path, contents)

    on_exit(fn -> File.rm(path) end)

    path
  end
end
