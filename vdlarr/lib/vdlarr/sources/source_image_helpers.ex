defmodule Vdlarr.Sources.SourceImageHelpers do
  @moduledoc """
  Helpers for resolving which poster image (if any) to display for a source.
  """

  import Ecto.Query

  alias Vdlarr.Repo
  alias Vdlarr.Media.MediaItem
  alias Vdlarr.Metadata.SourceMetadata
  alias Vdlarr.Metadata.MediaMetadata

  @doc """
  Returns the filepath of the best available poster image for a source.

  Checks, in order: a manually-uploaded custom poster (`source.custom_poster_filepath`
  - set only via SourceController.upload_poster/2, never touched by the auto-indexing
  pipeline, so it always wins and survives re-indexing), then the source's own
  library-copy poster (`source.poster_filepath`, only present when the source's
  media profile has `download_source_images` enabled), then the app's internal
  metadata directory copy (`source.metadata.poster_filepath`, populated
  unconditionally during indexing), then its fanart, then finally one of its
  media items' own thumbnail - so most sources show a real image rather than a
  placeholder even before opting into `download_source_images`.

  That last fallback matters most for `:video` sources: they never get
  channel/playlist-level art at all (see
  `Sources.maybe_run_metadata_storage_task/2` - there's no "series" to fetch
  avatar/banner art for), so without it a single video shows a placeholder even
  after its own thumbnail has downloaded successfully.

  Returns: filepath | nil
  """
  def poster_filepath(source) do
    source_with_preloads = Repo.preload(source, :metadata)
    source_metadata = source_with_preloads.metadata || %SourceMetadata{}

    [
      source_with_preloads.custom_poster_filepath,
      source_with_preloads.poster_filepath,
      source_metadata.poster_filepath,
      source_metadata.fanart_filepath,
      media_item_thumbnail_filepath(source_with_preloads)
    ]
    |> Enum.reject(&is_nil/1)
    |> Enum.find(&File.exists?/1)
  end

  defp media_item_thumbnail_filepath(source) do
    from(mi in MediaItem,
      join: metadata in MediaMetadata,
      on: metadata.media_item_id == mi.id,
      where: mi.source_id == ^source.id and not is_nil(metadata.thumbnail_filepath),
      order_by: [desc: mi.uploaded_at],
      select: metadata.thumbnail_filepath,
      limit: 1
    )
    |> Repo.one()
  end
end
