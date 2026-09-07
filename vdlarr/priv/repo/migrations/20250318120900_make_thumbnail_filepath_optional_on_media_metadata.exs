defmodule Vdlarr.Repo.Migrations.MakeThumbnailFilepathOptionalOnMediaMetadata do
  use Ecto.Migration

  # A failed thumbnail fetch (network blip, rate limit, an age-gated video's separate
  # thumbnail request hitting the same restriction as the main download, etc) is a real,
  # non-error outcome - not something that should block saving the rest of a successful
  # download's metadata. See MediaDownloader.download_for_media_item/2 and
  # MediaMetadata's thumbnail_filepath comment.
  #
  # SQLite has no ALTER COLUMN, so relaxing this NOT NULL constraint means rebuilding the
  # table - the standard SQLite approach (see https://sqlite.org/lang_altertable.html).
  def change do
    execute("""
      CREATE TABLE media_metadata_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        media_item_id INTEGER NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
        metadata_filepath TEXT NOT NULL,
        thumbnail_filepath TEXT,
        inserted_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
      )
    """)

    execute("""
      INSERT INTO media_metadata_new (id, media_item_id, metadata_filepath, thumbnail_filepath, inserted_at, updated_at)
      SELECT id, media_item_id, metadata_filepath, thumbnail_filepath, inserted_at, updated_at FROM media_metadata
    """)

    execute("DROP TABLE media_metadata")
    execute("ALTER TABLE media_metadata_new RENAME TO media_metadata")

    create unique_index(:media_metadata, [:media_item_id])
  end
end
