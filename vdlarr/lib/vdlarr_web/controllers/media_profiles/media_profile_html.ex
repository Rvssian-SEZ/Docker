defmodule VdlarrWeb.MediaProfiles.MediaProfileHTML do
  use VdlarrWeb, :html

  alias Vdlarr.Profiles.MediaProfile

  embed_templates "media_profile_html/*"

  @doc """
  Renders a media_profile form.
  """
  attr :changeset, Ecto.Changeset, required: true
  attr :action, :string, required: true
  attr :method, :string, required: true

  def media_profile_form(assigns)

  @doc """
  Root folder choices for the media profile form - the default root (MEDIA_PATH) first.
  """
  def root_folder_options do
    default = {"Default (#{Vdlarr.RootFolders.default_path()})", ""}
    [default | Enum.map(Vdlarr.RootFolders.list_root_folders(), &{"#{&1.name} (#{&1.path})", &1.id})]
  end

  @doc """
  The folder part of an output path template, eg: "/{{ source_custom_name }}/{{ title }}.{{ ext }}"
  -> "{{ source_custom_name }}/". Files land under the media root plus this.
  """
  def download_folder_label(template, root_name \\ nil)

  def download_folder_label(template, root_name) when is_binary(template) do
    root = root_name || "Default"

    case template |> String.trim_leading("/") |> Path.dirname() do
      "." -> root
      dir -> "#{root} › #{dir}/"
    end
  end

  def download_folder_label(_, root_name), do: root_name || "Default"

  @doc """
  The absolute folder a profile's files land under (its root plus the template's folders).
  """
  def download_folder_path(media_profile) do
    base = Vdlarr.RootFolders.base_path_for(media_profile)

    case media_profile.output_path_template |> String.trim_leading("/") |> Path.dirname() do
      "." -> base
      dir -> Path.join(base, dir) <> "/"
    end
  end

  def subtitles_label(%{download_subs: false, download_auto_subs: false}), do: "Off"

  def subtitles_label(profile) do
    kinds = if profile.download_auto_subs, do: "including auto-generated", else: "uploaded only"
    where = if profile.embed_subs, do: "embedded", else: "saved alongside"

    "#{String.capitalize(where)}, #{kinds} · #{profile.sub_langs}"
  end

  def short_subtitles_label(%{download_subs: false, download_auto_subs: false}), do: "Off"
  def short_subtitles_label(%{embed_subs: true}), do: "Embedded"
  def short_subtitles_label(_), do: "Saved alongside"

  def thumbnail_label(%{download_thumbnail: true, embed_thumbnail: true}), do: "Saved alongside and embedded"
  def thumbnail_label(%{download_thumbnail: true}), do: "Saved alongside"
  def thumbnail_label(%{embed_thumbnail: true}), do: "Embedded"
  def thumbnail_label(_), do: "Off"

  def metadata_label(profile) do
    [
      profile.embed_metadata && "Embedded",
      profile.download_metadata && "JSON saved alongside",
      profile.download_nfo && "NFO file"
    ]
    |> Enum.reject(&(&1 in [nil, false]))
    |> case do
      [] -> "Off"
      parts -> Enum.join(parts, " · ")
    end
  end

  def sponsorblock_label(%{sponsorblock_behaviour: :disabled}), do: "Off"

  def sponsorblock_label(%{sponsorblock_behaviour: behaviour, sponsorblock_categories: categories}) do
    action = if behaviour == :remove, do: "Remove", else: "Mark as chapters"

    case categories do
      [] -> action
      categories -> "#{action}: #{Enum.join(categories, ", ")}"
    end
  end

  def short_sponsorblock_label(%{sponsorblock_behaviour: :remove}), do: "Remove"
  def short_sponsorblock_label(%{sponsorblock_behaviour: :mark}), do: "Mark"
  def short_sponsorblock_label(_), do: "Off"

  def content_label(:only, kind), do: "Only #{kind}"
  def content_label(:exclude, kind), do: "Skip #{kind}"
  def content_label(_, kind), do: "Include #{kind}"

  def redownload_label(1), do: "Re-download 1 day after upload for better quality"

  def redownload_label(days) when is_integer(days) and days > 0,
    do: "Re-download #{days} days after upload for better quality"

  def redownload_label(_), do: "Off"

  def friendly_format_type_options do
    [
      {"Include (default)", :include},
      {"Exclude", :exclude},
      {"Only", :only}
    ]
  end

  def friendly_resolution_options do
    [
      {"8k", "4320p"},
      {"4k", "2160p"},
      {"1440p", "1440p"},
      {"1080p", "1080p"},
      {"720p", "720p"},
      {"480p", "480p"},
      {"360p", "360p"},
      {"Audio Only", "audio"}
    ]
  end

  def friendly_sponsorblock_options do
    [
      {"Disabled (default)", "disabled"},
      {"Mark Segments as Chapters", "mark"},
      {"Remove Segments", "remove"}
    ]
  end

  def frieldly_sponsorblock_categories do
    [
      {"Sponsor", "sponsor"},
      {"Intro/Intermission", "intro"},
      {"Outro/Credits", "outro"},
      {"Self Promotion", "selfpromo"},
      {"Preview/Recap", "preview"},
      {"Filler Tangent", "filler"},
      {"Interaction Reminder", "interaction"},
      {"Non-music Section", "music_offtopic"}
    ]
  end

  def media_center_custom_output_template_options do
    [
      season_by_year__episode_by_date: "<code>Season YYYY/sYYYYeMMDD</code>",
      season_by_year__episode_by_date_and_index:
        "same as the above but it handles dates better. <strong>This is the recommended option</strong>",
      static_season__episode_by_index:
        "<code>Season 1/s01eXX</code> where <code>XX</code> is the video's position in the playlist. Only recommended for playlists (not channels) that don't change",
      static_season__episode_by_date:
        "<code>Season 1/s01eYYMMDD</code>. Recommended for playlists that might change or where order isn't important"
    ]
  end

  def other_custom_output_template_options do
    [
      upload_day: nil,
      upload_month: nil,
      upload_year: nil,
      upload_yyyy_mm_dd: "the upload date in the format <code>YYYY-MM-DD</code>",
      source_custom_name: "the name of the sources that use this profile",
      source_collection_id: "the YouTube ID of the sources that use this profile",
      source_collection_name:
        "the YouTube name of the sources that use this profile (often the same as source_custom_name)",
      source_collection_type: "the collection type of the sources using this profile. One of 'channel', 'playlist', or 'video'",
      artist_name: "the name of the artist with fallbacks to other uploader fields",
      season_from_date: "alias for upload_year",
      season_episode_from_date: "the upload date formatted as <code>sYYYYeMMDD</code>",
      season_episode_index_from_date:
        "the upload date formatted as <code>sYYYYeMMDDII</code> where <code>II</code> is an index to prevent date collisions",
      media_playlist_index:
        "the place of the media item in the playlist. Do not use with channels. May not work if the playlist is updated",
      media_item_id: "the ID of the media item in Vdlarr's database",
      source_id: "the ID of the source in Vdlarr's database",
      media_profile_id: "the ID of the media profile in Vdlarr's database"
    ]
  end

  def common_output_template_options do
    ~w(
      id
      ext
      title
      uploader
      channel
      upload_date
      duration_string
    )a
  end

  def preset_options do
    [
      {"Default", "default"},
      {"Media Center (Plex, Jellyfin, Kodi, etc.)", "media_center"},
      {"Music", "audio"},
      {"Archiving", "archiving"}
    ]
  end

  defp default_output_template do
    %MediaProfile{}.output_path_template
  end

  defp media_center_output_template do
    "/shows/{{ source_custom_name }}/{{ season_by_year__episode_by_date_and_index }} - {{ title }}.{{ ext }}"
  end

  defp audio_output_template do
    "/music/{{ artist_name }}/{{ title }}.{{ ext }}"
  end
end
