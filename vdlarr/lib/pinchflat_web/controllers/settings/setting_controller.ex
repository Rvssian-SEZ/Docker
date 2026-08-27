defmodule PinchflatWeb.Settings.SettingController do
  use PinchflatWeb, :controller

  alias Pinchflat.Settings
  alias Pinchflat.Lifecycle.Notifications.JellyfinNotifier

  def show(conn, _params) do
    setting = Settings.record()
    changeset = Settings.change_setting(setting)

    render(conn, "show.html", changeset: changeset)
  end

  def update(conn, %{"setting" => setting_params}) do
    setting = Settings.record()

    case Settings.update_setting(setting, setting_params) do
      {:ok, _} ->
        conn
        |> put_flash(:info, "Settings updated successfully.")
        |> redirect(to: ~p"/settings")

      {:error, %Ecto.Changeset{} = changeset} ->
        render(conn, "show.html", changeset: changeset)
    end
  end

  @doc """
  Tests the currently-saved Jellyfin URL/API key (save your changes first). Kept as a
  plain form POST (rather than an AJAX call with unsaved field values) so it reuses
  the same CSRF-protected POST flow as every other action button in this app.
  """
  def test_jellyfin_connection(conn, _params) do
    url = Settings.get!(:jellyfin_url)
    api_key = Settings.get!(:jellyfin_api_key)

    case JellyfinNotifier.test_connection(url, api_key) do
      {:ok, message} -> conn |> put_flash(:info, message) |> redirect(to: ~p"/settings")
      {:error, message} -> conn |> put_flash(:error, "Jellyfin connection failed: #{message}") |> redirect(to: ~p"/settings")
    end
  end

  def app_info(conn, _params) do
    render(conn, "app_info.html")
  end

  def download_logs(conn, _params) do
    log_path = Application.get_env(:pinchflat, :log_path)

    if log_path && File.exists?(log_path) do
      send_download(conn, {:file, log_path}, filename: "pinchflat-logs-#{Date.utc_today()}.txt")
    else
      conn
      |> put_flash(:error, "Log file couldn't be found")
      |> redirect(to: ~p"/app_info")
    end
  end
end
