defmodule Vdlarr.Lifecycle.Notifications.JellyfinNotifier do
  @moduledoc """
  Notifies a Jellyfin media server about newly downloaded media, so it picks up new
  files immediately instead of waiting for its own periodic library scan - the same
  approach Sonarr/Radarr use for their Jellyfin/Emby notification connections.

  Uses `POST /Library/Media/Updated`, which asks Jellyfin to check just the given
  path(s) rather than triggering a full library rescan. See:
  https://api.jellyfin.org/openapi/jellyfin-openapi-stable.json (LibraryController)
  """

  require Logger

  alias Vdlarr.Settings
  alias Vdlarr.Media.MediaItem

  @doc """
  Tells Jellyfin about a newly downloaded media item. No-ops (returns :ok) if
  Jellyfin isn't configured (blank url/api key), matching the blank-disables
  convention already used for Apprise notifications.

  Returns :ok
  """
  def notify_new_media(%MediaItem{} = media_item) do
    with {:ok, url, api_key} <- jellyfin_config() do
      path = remap_path(media_item.media_filepath)
      body = Phoenix.json_library().encode!(%{"Updates" => [%{"Path" => path, "UpdateType" => "Created"}]})

      case http_client().post(join_url(url, "/Library/Media/Updated"), body, request_headers(api_key), http_opts()) do
        {:ok, _response} ->
          Logger.info("Notified Jellyfin about new media: #{path}")

        {:error, reason} ->
          Logger.error("Failed to notify Jellyfin about new media: #{reason}")
      end
    end

    :ok
  end

  @doc """
  Checks that the given Jellyfin URL/API key are reachable and valid, for the
  Settings page's "Test Connection" button. Takes the values directly (rather than
  reading from Settings) so the user can test before saving.

  Returns {:ok, binary()} | {:error, binary()}
  """
  def test_connection(url, api_key) when is_binary(url) and url != "" and is_binary(api_key) and api_key != "" do
    case http_client().get(join_url(url, "/System/Info"), request_headers(api_key), http_opts()) do
      {:ok, _response} -> {:ok, "Connected to Jellyfin successfully"}
      {:error, reason} -> {:error, reason}
    end
  end

  def test_connection(_url, _api_key), do: {:error, "URL and API key are both required"}

  defp jellyfin_config do
    url = Settings.get!(:jellyfin_url)
    api_key = Settings.get!(:jellyfin_api_key)

    if is_binary(url) and url != "" and is_binary(api_key) and api_key != "" do
      {:ok, url, api_key}
    else
      :error
    end
  end

  # If Jellyfin sees this library at a different container path than we do (eg: two
  # different containers mounting the same host directory at different paths), swap
  # our media_directory prefix for the configured Jellyfin-side prefix. Otherwise,
  # assume both containers mount the same path and send it unchanged.
  defp remap_path(filepath) do
    case Settings.get!(:jellyfin_path_prefix) do
      prefix when is_binary(prefix) and prefix != "" ->
        media_directory = Application.get_env(:vdlarr, :media_directory)
        String.replace_prefix(filepath, media_directory, prefix)

      _ ->
        filepath
    end
  end

  defp request_headers(api_key) do
    [
      {"content-type", "application/json"},
      {"authorization", ~s(MediaBrowser Token="#{api_key}")},
      {"x-mediabrowser-token", api_key}
    ]
  end

  defp join_url(base_url, path) do
    String.trim_trailing(base_url, "/") <> path
  end

  defp http_opts do
    [timeout: 10_000]
  end

  defp http_client do
    Application.get_env(:vdlarr, :http_client)
  end
end
