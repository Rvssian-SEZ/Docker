defmodule Vdlarr.Settings.Setting do
  @moduledoc """
  The Setting schema.
  """

  use Ecto.Schema
  import Ecto.Changeset

  @allowed_fields [
    :yt_dlp_version,
    :apprise_version,
    :apprise_server,
    :video_codec_preference,
    :audio_codec_preference,
    :extractor_sleep_interval_seconds,
    :download_throughput_limit,
    :restrict_filenames,
    :show_hidden_sources_menu,
    :timezone,
    :jellyfin_url,
    :jellyfin_api_key,
    :jellyfin_path_prefix,
    :bgutil_provider_url
  ]

  @required_fields [
    :video_codec_preference,
    :audio_codec_preference,
    :extractor_sleep_interval_seconds
  ]

  schema "settings" do
    field :yt_dlp_version, :string
    field :apprise_version, :string
    field :apprise_server, :string
    field :route_token, :string
    field :extractor_sleep_interval_seconds, :integer, default: 0
    # This is a string because it accepts values like "100K" or "4.2M"
    field :download_throughput_limit, :string
    field :restrict_filenames, :boolean, default: false
    field :show_hidden_sources_menu, :boolean, default: true
    # Nullable on purpose - nil means "not yet seeded from the TZ/TIMEZONE env var".
    # See Vdlarr.Boot.PreJobStartupTasks
    field :timezone, :string

    # Optional - blank disables Jellyfin notifications, matching apprise_server's convention.
    field :jellyfin_url, :string
    field :jellyfin_api_key, :string
    # Only needed if Jellyfin's mount path for the library differs from this app's
    # media_directory - see Vdlarr.Lifecycle.Notifications.JellyfinNotifier
    field :jellyfin_path_prefix, :string

    # Optional - base URL of a bgutil-ytdlp-pot-provider HTTP server (see
    # Vdlarr.YtDlp.BgutilPluginUpdateWorker). Blank disables the plugin
    # version-sync check, matching apprise_server/jellyfin_url's convention.
    field :bgutil_provider_url, :string

    field :video_codec_preference, :string
    field :audio_codec_preference, :string
  end

  @doc false
  def changeset(setting, attrs) do
    setting
    |> cast(attrs, @allowed_fields)
    |> validate_required(@required_fields)
    |> validate_number(:extractor_sleep_interval_seconds, greater_than_or_equal_to: 0)
    |> validate_timezone()
  end

  defp validate_timezone(changeset) do
    validate_change(changeset, :timezone, fn :timezone, tz ->
      if Tzdata.zone_exists?(tz), do: [], else: [timezone: "is not a recognized timezone"]
    end)
  end
end
