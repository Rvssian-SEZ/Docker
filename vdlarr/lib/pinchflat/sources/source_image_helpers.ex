defmodule Pinchflat.Sources.SourceImageHelpers do
  @moduledoc """
  Helpers for resolving which poster image (if any) to display for a source.
  """

  alias Pinchflat.Repo
  alias Pinchflat.Metadata.SourceMetadata

  @doc """
  Returns the filepath of the best available poster image for a source.

  Checks, in order: a manually-uploaded custom poster (`source.custom_poster_filepath`
  - set only via SourceController.upload_poster/2, never touched by the auto-indexing
  pipeline, so it always wins and survives re-indexing), then the source's own
  library-copy poster (`source.poster_filepath`, only present when the source's
  media profile has `download_source_images` enabled), then the app's internal
  metadata directory copy (`source.metadata.poster_filepath`, populated
  unconditionally during indexing), then its fanart as a last resort - so most
  sources show a real image rather than a placeholder even before opting into
  `download_source_images`.

  Returns: filepath | nil
  """
  def poster_filepath(source) do
    source_with_preloads = Repo.preload(source, :metadata)
    source_metadata = source_with_preloads.metadata || %SourceMetadata{}

    [
      source_with_preloads.custom_poster_filepath,
      source_with_preloads.poster_filepath,
      source_metadata.poster_filepath,
      source_metadata.fanart_filepath
    ]
    |> Enum.reject(&is_nil/1)
    |> Enum.find(&File.exists?/1)
  end
end
