defmodule VdlarrWeb.Settings.SettingController do
  use VdlarrWeb, :controller

  alias Vdlarr.Settings
  alias Vdlarr.RootFolders
  alias Vdlarr.YtDlp.UpdateWorker
  alias Vdlarr.Lifecycle.Notifications.JellyfinNotifier

  @yt_dlp_policy_fields [:yt_dlp_update_policy, :yt_dlp_pinned_version]

  def show(conn, _params) do
    setting = Settings.record()
    changeset = Settings.change_setting(setting)

    render(conn, "show.html", [changeset: changeset] ++ root_folder_assigns())
  end

  defp root_folder_assigns do
    default_path = RootFolders.default_path()

    roots =
      Enum.map(RootFolders.list_root_folders(), fn root ->
        %{root: root, free: RootFolders.free_bytes(root.path), profiles: RootFolders.profile_count(root)}
      end)

    [
      root_folders: roots,
      default_root: %{path: default_path, free: RootFolders.free_bytes(default_path), jellyfin: Settings.get!(:jellyfin_path_prefix)},
      root_folder_changeset: RootFolders.change_root_folder(%Vdlarr.RootFolders.RootFolder{})
    ]
  end

  def update(conn, %{"setting" => setting_params}) do
    setting = Settings.record()

    case Settings.update_setting(setting, setting_params) do
      {:ok, updated_setting} ->
        maybe_apply_yt_dlp_policy(setting, updated_setting)

        conn
        |> put_flash(:info, "Settings updated successfully.")
        |> redirect(to: ~p"/settings")

      {:error, %Ecto.Changeset{} = changeset} ->
        render(conn, "show.html", [changeset: changeset] ++ root_folder_assigns())
    end
  end

  # yt-dlp's own binary lives on the container's ephemeral filesystem, and the update
  # policy determines which channel/version it should be on - so a policy change needs
  # to actually trigger an update, not just save the new preference. Kicked off as a
  # background job (not run inline here) so the settings save itself stays fast.
  defp maybe_apply_yt_dlp_policy(old_setting, new_setting) do
    changed? = Enum.any?(@yt_dlp_policy_fields, &(Map.get(old_setting, &1) != Map.get(new_setting, &1)))

    if changed?, do: UpdateWorker.kickoff_apply()
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

  # Only the tail is read - the log file can grow up to 10MB per the rotating file handler
  # config (see config/runtime.exs). It's generous because at debug level most of it is
  # filtered out; the page itself shows at most @max_log_entries entries. The full file is
  # always available via download.
  @max_log_display_bytes 3_000_000

  @log_levels ~w(debug info warning error)
  @max_log_entries 1_000

  @doc """
  Shows recent log entries at or above the chosen level (default: info), newest first.
  Production logs at debug by default (see LOG_LEVEL), which buries warnings and errors under
  SQL and request noise - so entries are parsed out of the raw file and filtered here.
  """
  def logs(conn, params) do
    log_path = Application.get_env(:vdlarr, :log_path)
    level = if params["level"] in @log_levels, do: params["level"], else: "info"

    entries =
      case read_log_tail(log_path) do
        nil -> nil
        content -> content |> parse_log_entries() |> filter_log_level(level) |> Enum.take(-@max_log_entries) |> Enum.reverse()
      end

    render(conn, "logs.html", log_entries: entries, level: level, logger_level: Logger.level())
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

  @log_entry_start ~r/^\S*\s*\d{2}:\d{2}:\d{2}(?:\.\d+)?\s+\[(debug|info|notice|warning|warn|error|critical|alert|emergency)\]/

  # A new entry starts at a timestamped "[level]" line; anything else (SQL, stack traces,
  # command output) is a continuation of the entry above it.
  defp parse_log_entries(content) do
    content
    |> String.split("\n")
    |> Enum.reduce([], fn line, acc ->
      case Regex.run(@log_entry_start, line) do
        [_, level] -> [%{level: normalize_level(level), text: line} | acc]
        nil when acc == [] -> acc
        nil -> [Map.update!(hd(acc), :text, &(&1 <> "\n" <> line)) | tl(acc)]
      end
    end)
    |> Enum.reverse()
    |> Enum.map(&Map.update!(&1, :text, fn text -> String.trim_trailing(text) end))
  end

  defp normalize_level("warn"), do: "warning"
  defp normalize_level(level) when level in ["critical", "alert", "emergency"], do: "error"
  defp normalize_level("notice"), do: "info"
  defp normalize_level(level), do: level

  defp filter_log_level(entries, level) do
    min_rank = Enum.find_index(@log_levels, &(&1 == level))

    Enum.filter(entries, fn %{level: entry_level} ->
      Enum.find_index(@log_levels, &(&1 == entry_level)) >= min_rank
    end)
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
