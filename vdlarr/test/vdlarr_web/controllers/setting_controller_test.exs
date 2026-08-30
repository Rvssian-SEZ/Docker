defmodule VdlarrWeb.SettingControllerTest do
  use VdlarrWeb.ConnCase

  alias Vdlarr.Settings
  alias Vdlarr.Utils.FilesystemUtils

  describe "show settings" do
    test "renders the page", %{conn: conn} do
      conn = get(conn, ~p"/settings")

      assert html_response(conn, 200) =~ "Settings"
    end
  end

  describe "update settings" do
    test "saves and redirects when data is valid", %{conn: conn} do
      update_attrs = %{apprise_server: "test://server"}

      conn = put(conn, ~p"/settings", setting: update_attrs)
      assert redirected_to(conn) == ~p"/settings"

      conn = get(conn, ~p"/settings")
      assert html_response(conn, 200) =~ update_attrs[:apprise_server]
    end
  end

  describe "test_jellyfin_connection" do
    setup do
      on_exit(fn ->
        Settings.set(jellyfin_url: nil)
        Settings.set(jellyfin_api_key: nil)
      end)

      :ok
    end

    test "flashes success and redirects when the connection succeeds", %{conn: conn} do
      Settings.set(jellyfin_url: "http://jellyfin.local:8096")
      Settings.set(jellyfin_api_key: "abc123")

      expect(HTTPClientMock, :get, fn _url, _headers, _opts -> {:ok, "{}"} end)

      conn = post(conn, ~p"/settings/test_jellyfin_connection")

      assert redirected_to(conn) == ~p"/settings"
      assert conn.assigns[:flash]["info"]
    end

    test "flashes an error and redirects when the connection fails", %{conn: conn} do
      Settings.set(jellyfin_url: "http://jellyfin.local:8096")
      Settings.set(jellyfin_api_key: "abc123")

      expect(HTTPClientMock, :get, fn _url, _headers, _opts -> {:error, "unauthorized"} end)

      conn = post(conn, ~p"/settings/test_jellyfin_connection")

      assert redirected_to(conn) == ~p"/settings"
      assert conn.assigns[:flash]["error"] =~ "unauthorized"
    end
  end

  describe "logs" do
    test "renders the page", %{conn: conn} do
      conn = get(conn, ~p"/logs")

      assert html_response(conn, 200) =~ "Logs"
    end

    test "renders the tail of the log file when present", %{conn: conn} do
      log_path = Path.join([System.tmp_dir!(), "vdlarr", "data", "vdlarr.log"])
      FilesystemUtils.write_p(log_path, "test log data")
      Application.put_env(:vdlarr, :log_path, log_path)

      conn = get(conn, ~p"/logs")

      assert html_response(conn, 200) =~ "test log data"

      Application.put_env(:vdlarr, :log_path, nil)
    end
  end

  describe "download_logs" do
    test "downloads logs", %{conn: conn} do
      log_path = Path.join([System.tmp_dir!(), "vdlarr", "data", "vdlarr.log"])
      FilesystemUtils.write_p(log_path, "test log data")
      Application.put_env(:vdlarr, :log_path, log_path)

      conn = get(conn, ~p"/download_logs")

      assert response(conn, 200) =~ "test log data"

      Application.put_env(:vdlarr, :log_path, nil)
    end

    test "redirects when log file is not found", %{conn: conn} do
      conn = get(conn, ~p"/download_logs")

      assert redirected_to(conn) == ~p"/logs"
      assert conn.assigns[:flash]["error"] == "Log file couldn't be found"
    end
  end
end
