defmodule Vdlarr.Metadata.MediaMetadata do
  @moduledoc """
  The MediaMetadata schema.

  Look. Don't @ me about Metadata vs. Metadatum. I'm very sensitive.
  """

  use Ecto.Schema
  import Ecto.Changeset

  alias Vdlarr.Media.MediaItem

  @allowed_fields ~w(metadata_filepath thumbnail_filepath)a
  # thumbnail_filepath is allowed but not required - MetadataFileHelpers.download_and_store_thumbnail_for/1
  # returns nil whenever the thumbnail-fetch yt-dlp call fails (network blip, rate limit, an
  # age-gated video's separate thumbnail request hitting the same restriction as the main
  # download, etc), which is a real, non-error outcome - not something that should block saving
  # the rest of a successful download's metadata. Callers already treat a nil/missing thumbnail
  # as a normal case (see PodcastHelpers.get_images_by_preference/2's fallback chain).
  @required_fields ~w(metadata_filepath)a

  schema "media_metadata" do
    field :metadata_filepath, :string
    field :thumbnail_filepath, :string

    belongs_to :media_item, MediaItem

    timestamps(type: :utc_datetime)
  end

  @doc false
  def changeset(media_metadata, attrs) do
    media_metadata
    |> cast(attrs, @allowed_fields)
    |> validate_required(@required_fields)
    |> unique_constraint([:media_item_id])
  end

  @doc false
  def filepath_attributes do
    ~w(metadata_filepath thumbnail_filepath)a
  end
end
