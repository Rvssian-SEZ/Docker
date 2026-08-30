defmodule Vdlarr.YtDlp.BgutilPluginUpdateWorker do
  @moduledoc """
  Keeps the bgutil-ytdlp-pot-provider yt-dlp plugin in sync with whatever version
  the configured PO Token Provider server actually reports itself as running.

  The provider's docker image is commonly pinned to `:latest` and updates itself
  independently of this app, but the yt-dlp PLUGIN files are static, manually-installed
  files - nothing keeps them in sync automatically. A mismatch between the two doesn't
  necessarily hard-fail every request, but it can silently break specific client
  fallback paths that need a correctly-versioned PO token (this is exactly what
  happened in production: the only successful extraction path for an age-restricted
  video needs a `web_creator`-scoped token, and a mismatched plugin was silently
  failing to request one correctly until the versions were manually re-aligned).

  Syncs to whatever the server itself reports via `/ping`, not "latest on GitHub" -
  this stays correct even if the provider is pinned to an older tag.

  No-ops entirely if `Settings.get!(:bgutil_provider_url)` isn't configured - this is
  optional companion infrastructure, not a hard dependency of this app.
  """

  use Oban.Worker,
    queue: :local_data,
    tags: ["local_data"]

  require Logger

  alias Vdlarr.Settings

  @plugin_files ~w(getpot_bgutil.py getpot_bgutil_http.py getpot_bgutil_script.py)
  @release_url_base "https://github.com/Brainicism/bgutil-ytdlp-pot-provider/releases/download"

  @doc """
  Starts the worker. Does not attach it to a task like `kickoff_with_task/2`.

  Returns {:ok, %Oban.Job{}} | {:error, %Ecto.Changeset{}}
  """
  def kickoff do
    Oban.insert(__MODULE__.new(%{}))
  end

  @impl Oban.Worker
  def perform(%Oban.Job{}) do
    case Settings.get!(:bgutil_provider_url) do
      blank when blank in [nil, ""] -> :ok
      base_url -> sync_plugin_version(base_url)
    end
  end

  defp sync_plugin_version(base_url) do
    case fetch_server_version(base_url) do
      {:ok, server_version} ->
        maybe_update_plugin(server_version)

      {:error, reason} ->
        Logger.warning("Couldn't check bgutil-provider version, skipping plugin sync: #{inspect(reason)}")
        :ok
    end
  end

  defp maybe_update_plugin(server_version) do
    installed_version = installed_plugin_version()

    if server_version == installed_version do
      :ok
    else
      Logger.info(
        "bgutil-ytdlp-pot-provider plugin/server version mismatch " <>
          "(plugin: #{installed_version || "none"}, server: #{server_version}) - updating plugin"
      )

      update_plugin_to_version(server_version)
    end
  end

  defp fetch_server_version(base_url) do
    with {:ok, body} <- http_client().get("#{base_url}/ping", [], []),
         {:ok, %{"version" => version}} <- Phoenix.json_library().decode(body) do
      {:ok, version}
    else
      {:error, reason} -> {:error, reason}
      _ -> {:error, "unexpected /ping response shape"}
    end
  end

  defp installed_plugin_version do
    case File.read(plugin_filepath("getpot_bgutil.py")) do
      {:ok, content} ->
        case Regex.run(~r/__version__\s*=\s*['"]([\d.]+)['"]/, content) do
          [_, version] -> version
          _ -> nil
        end

      {:error, _} ->
        nil
    end
  end

  defp update_plugin_to_version(version) do
    tmp_dir = Path.join(System.tmp_dir!(), "bgutil-plugin-update-#{:erlang.unique_integer([:positive])}")

    try do
      download_and_install_plugin(version, tmp_dir)
    after
      File.rm_rf(tmp_dir)
    end
  end

  defp download_and_install_plugin(version, tmp_dir) do
    zip_path = Path.join(tmp_dir, "plugin.zip")
    File.mkdir_p!(tmp_dir)

    with {_, 0} <- System.cmd("curl", ["-sL", "-o", zip_path, release_url(version)]),
         {_, 0} <- System.cmd("unzip", ["-o", "-q", zip_path, "-d", tmp_dir]) do
      Enum.each(@plugin_files, fn filename ->
        source = Path.join([tmp_dir, "yt_dlp_plugins", "extractor", filename])
        install_plugin_file(source, filename)
      end)

      Logger.info("Updated bgutil-ytdlp-pot-provider plugin to version #{version}")
      :ok
    else
      {output, status} ->
        Logger.error(
          "Failed to download/extract bgutil-ytdlp-pot-provider plugin #{version}: #{output} (exit #{status})"
        )

        :ok
    end
  end

  defp install_plugin_file(source, filename) do
    if File.exists?(source) do
      destination = plugin_filepath(filename)
      File.mkdir_p!(Path.dirname(destination))
      File.cp!(source, destination)
    end
  end

  defp release_url(version) do
    "#{@release_url_base}/#{version}/bgutil-ytdlp-pot-provider.zip"
  end

  defp plugin_filepath(filename) do
    Path.join([
      Application.get_env(:vdlarr, :yt_dlp_plugin_directory),
      "bgutil-ytdlp-pot-provider",
      "yt_dlp_plugins",
      "extractor",
      filename
    ])
  end

  defp http_client do
    Application.get_env(:vdlarr, :http_client)
  end
end
