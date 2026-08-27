defmodule Pinchflat.Repo.Migrations.AddExtractorToMediaItems do
  use Ecto.Migration

  def change do
    alter table(:media_items) do
      add :extractor, :string
    end
  end
end
