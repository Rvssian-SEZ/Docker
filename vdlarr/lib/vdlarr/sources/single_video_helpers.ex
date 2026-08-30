defmodule Vdlarr.Sources.SingleVideoHelpers do
  @moduledoc """
  Handles creating a `:video`-type Source from a bare video URL (as opposed to
  a channel or playlist URL). Unlike channel/playlist sources, a `:video` source
  is indexed exactly once - see the `collection_type == :video` short-circuit in
  `SlowIndexingHelpers` for how its single MediaItem actually gets created and
  its download enqueued.
  """

  alias Vdlarr.Sources
  alias Vdlarr.YtDlp.Media, as: YtDlpMedia

  @doc """
  Creates a `:video`-type Source for a single video URL. Fetches the video's
  metadata up front (to populate the source's name/collection details, same
  as channel/playlist sources do today), then defers to the normal indexing
  worker (kicked off automatically by `Sources.create_source_from_params/2`) to
  create the MediaItem and enqueue its download.

  `attrs` follows the same string-keyed convention as a normal Phoenix form
  submission (ie: what `SourceController.create_video/2` receives directly from
  the request) and can include any normally-allowed
  Source field (e.g. `"custom_name"`, `"download_media"`, `"cookie_behaviour"`,
  `"media_profile_id"`) - `original_url`, `collection_type`, `collection_id`,
  `collection_name`, and `index_frequency_minutes` are always set by this
  function and cannot be overridden by `attrs`.

  Returns {:ok, %Source{}} | {:error, %Ecto.Changeset{}} | {:error, any()}
  """
  def create_source(url, attrs \\ %{}) do
    should_use_cookies = Map.get(attrs, "cookie_behaviour") == "all_operations"

    case YtDlpMedia.get_media_attributes(url, [], use_cookies: should_use_cookies) do
      {:ok, media_attrs} ->
        source_attrs =
          Map.merge(attrs, %{
            "original_url" => url,
            "collection_type" => "video",
            "collection_id" => media_attrs.media_id,
            "collection_name" => media_attrs.title,
            # Videos are indexed exactly once - there's nothing to re-check later.
            # See `MediaCollectionIndexingWorker.perform/1`: a source that's never
            # been indexed always gets indexed once regardless of this value, then
            # (since it's not > 0) never reschedules itself.
            "index_frequency_minutes" => -1
          })

        Sources.create_source_from_params(source_attrs)

      err ->
        err
    end
  end
end
