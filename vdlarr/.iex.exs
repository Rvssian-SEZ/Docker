import Ecto.Query, warn: false
alias Vdlarr.Repo

alias Vdlarr.Tasks.Task
alias Vdlarr.Sources.Source
alias Vdlarr.Media.MediaItem
alias Vdlarr.Metadata.MediaMetadata
alias Vdlarr.Profiles.MediaProfile

alias Vdlarr.Tasks
alias Vdlarr.Media
alias Vdlarr.Profiles
alias Vdlarr.Sources
alias Vdlarr.Settings

alias Vdlarr.Downloading.MediaDownloader
alias Vdlarr.YtDlp.Media, as: YtDlpMedia
alias Vdlarr.YtDlp.MediaCollection, as: YtDlpCollection

alias Vdlarr.FastIndexing.YoutubeRss
alias Vdlarr.Metadata.MetadataFileHelpers

alias Vdlarr.SlowIndexing.FileFollowerServer

Vdlarr.Release.check_file_permissions()

defmodule IexHelpers do
  def restart do
    :init.restart()
  end
end

import IexHelpers
