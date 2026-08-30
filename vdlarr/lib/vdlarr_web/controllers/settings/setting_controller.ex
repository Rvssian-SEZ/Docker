defmodule VdlarrWeb.Settings.SettingController do
  use VdlarrWeb, :controller

  alias Vdlarr.Settings
  alias Vdlarr.Lifecycle.Notifications.JellyfinNotifier

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

  # Only the tail is rendered on the page - the log file can grow up to 10MB per the
  # rotating file handler config (see config/runtime.exs), and dumping all of that into
  # the DOM would make the page sluggish. The full file is always available via download.
  @max_log_display_bytes 300_000

  def logs(conn, _params) do
    log_path = Application.get_env(:vdlarr, :log_path)

    render(conn, "logs.html", log_content: read_log_tail(log_path))
  end

  def download_logs(conn, _params) do
    log_path = Application.get_env(:vdlarr, :log_path)

    if log_path && File.exists?(log_path) do
      send_download(conn, {:file, log_path}, filename: "vdlarr-logs-#{Date.utc_today()}.txt")
    else
      conn
      |> put_flash(:error, "Log file couldn't be found")
      |> redirect(to: ~p"/logs")
    end
  end

  defp read_log_tail(nil), do: nil

  defp read_log_tail(log_path) do
    case File.read(log_path) do
      {:ok, content} -> tail_from_line_boundary(content)
      {:error, _} -> nil
    end
  end

  defp tail_from_line_boundary(content) do
    size = byte_size(content)
    start = max(size - @max_log_display_bytes, 0)
    tail = :binary.part(content, start, size - start)

    case start > 0 && :binary.match(tail, "\n") do
      {pos, _} -> :binary.part(tail, pos + 1, byte_size(tail) - pos - 1)
      _ -> tail
    end
  end
end
