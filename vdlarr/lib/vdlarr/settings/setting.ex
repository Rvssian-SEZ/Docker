defmodule Vdlarr.Settings.Setting do
  @moduledoc """
  The Setting schema.
  """

  use Ecto.Schema
  import Ecto.Changeset

  alias Vdlarr.YtDlp.UpdateManager

  @allowed_fields [
    :yt_dlp_version,
    :yt_dlp_update_policy,
    :yt_dlp_pinned_version,
    :yt_dlp_nightly_baseline,
    :apprise_version,
    :apprise_server,
    :video_codec_preference,
    :audio_codec_preference,
    :extractor_sleep_interval_seconds,
    :indexing_sleep_interval_seconds,
    :download_throughput_limit,
    :restrict_filenames,
    :show_hidden_sources_menu,
    :ignore_unavailable_media,
    :timezone,
    :jellyfin_url,
    :jellyfin_api_key,
    :jellyfin_path_prefix,
    :bgutil_provider_url
  ]

  @required_fields [
    :video_codec_preference,
    :audio_codec_preference,
    :extractor_sleep_interval_seconds,
    :indexing_sleep_interval_seconds
  ]

  schema "settings" do
    field :yt_dlp_version, :string
    # See Vdlarr.YtDlp.UpdateManager for what each policy means
    field :yt_dlp_update_policy, :string, default: "stable"
    field :yt_dlp_pinned_version, :string
    # Records which exact nightly build a "nightly_frozen"/"nightly_until_stable"
    # jump landed on, so a later boot can re-assert that same build instead of
    # drifting to whatever the latest nightly happens to be at boot time
    field :yt_dlp_nightly_baseline, :string
    field :apprise_version, :string
    field :apprise_server, :string
    field :route_token, :string
    field :extractor_sleep_interval_seconds, :integer, default: 0
    # Independent from extractor_sleep_interval_seconds above - indexing (channel/playlist
    # listing and per-video metadata fetches) is a much lighter request than an actual media
    # download, so it's commonly safe to run it on a shorter interval. Defaults to something
    # noticeably faster than a typical download interval while still being polite to YouTube,
    # rather than defaulting to 0/disabled - most installs will want this on from the start.
    field :indexing_sleep_interval_seconds, :integer, default: 5
    # This is a string because it accepts values like "100K" or "4.2M"
    field :download_throughput_limit, :string
    field :restrict_filenames, :boolean, default: false
    field :show_hidden_sources_menu, :boolean, default: true
    # When true, a download that fails with a known "permanently unavailable" error
    # (private/removed/members-only, see Vdlarr.YtDlp.UnavailableMedia) is marked
    # prevent_download instead of just being left to fail forever
    field :ignore_unavailable_media, :boolean, default: false
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
    |> validate_number(:indexing_sleep_interval_seconds, greater_than_or_equal_to: 0)
    |> validate_timezone()
    |> validate_inclusion(:yt_dlp_update_policy, UpdateManager.policies())
  end

  defp validate_timezone(changeset) do
    validate_change(changeset, :timezone, fn :timezone, tz ->
      if Tzdata.zone_exists?(tz), do: [], else: [timezone: "is not a recognized timezone"]
    end)
  end
end
