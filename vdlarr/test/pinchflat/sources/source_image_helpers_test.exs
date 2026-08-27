defmodule Pinchflat.Sources.SourceImageHelpersTest do
  use Pinchflat.DataCase

  import Pinchflat.SourcesFixtures
  import Pinchflat.MediaFixtures

  alias Pinchflat.Sources.SourceImageHelpers

  describe "poster_filepath/1" do
    test "returns nil when the source has no poster anywhere" do
      source = source_fixture()

      assert SourceImageHelpers.poster_filepath(source) == nil
    end

    test "prefers the source's own library poster_filepath" do
      source = source_with_metadata_attachments(%{poster_filepath: thumbnail_filepath_fixture()})

      assert SourceImageHelpers.poster_filepath(source) == thumbnail_filepath_fixture()
    end

    test "falls back to the metadata poster when there's no library poster" do
      source = source_with_metadata_attachments()

      assert SourceImageHelpers.poster_filepath(source) == source.metadata.poster_filepath
    end

    test "falls back to the metadata fanart when there's no poster at all" do
      source = source_with_metadata_attachments()
      File.rm(source.metadata.poster_filepath)

      assert SourceImageHelpers.poster_filepath(source) == source.metadata.fanart_filepath
    end

    test "returns nil when the DB points at a file that no longer exists on disk" do
      source = source_with_metadata_attachments()
      File.rm(source.metadata.poster_filepath)
      File.rm(source.metadata.fanart_filepath)

      assert SourceImageHelpers.poster_filepath(source) == nil
    end
  end
end
