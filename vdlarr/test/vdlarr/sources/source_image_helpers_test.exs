defmodule Vdlarr.Sources.SourceImageHelpersTest do
  use Vdlarr.DataCase

  import Vdlarr.SourcesFixtures
  import Vdlarr.MediaFixtures

  alias Vdlarr.Sources.SourceImageHelpers

  describe "poster_filepath/1" do
    test "returns nil when the source has no poster anywhere" do
      source = source_fixture()

      assert SourceImageHelpers.poster_filepath(source) == nil
    end

    test "prefers a manually-uploaded custom poster over everything else" do
      source = source_with_metadata_attachments(%{custom_poster_filepath: thumbnail_filepath_fixture()})

      assert source.custom_poster_filepath != source.metadata.poster_filepath
      assert SourceImageHelpers.poster_filepath(source) == source.custom_poster_filepath
    end

    test "falls back to the auto-downloaded chain when the custom poster file is missing" do
      source = source_with_metadata_attachments(%{custom_poster_filepath: "/tmp/does-not-exist.jpg"})

      assert SourceImageHelpers.poster_filepath(source) == source.metadata.poster_filepath
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

    test "falls back to a media item's own thumbnail when the source has no art of its own" do
      source = source_fixture()
      media_item = media_item_with_metadata_attachments(%{source_id: source.id})

      assert SourceImageHelpers.poster_filepath(source) == media_item.metadata.thumbnail_filepath
    end

    test "prefers the metadata fanart over a media item's thumbnail" do
      source = source_with_metadata_attachments()
      media_item_with_metadata_attachments(%{source_id: source.id})

      assert SourceImageHelpers.poster_filepath(source) == source.metadata.poster_filepath
    end
  end
end
